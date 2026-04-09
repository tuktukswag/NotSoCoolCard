#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# GitHub Actions and other CI environments set CI=true.
# In CI we force tqdm to write newlines so each update appears as a log line.
CI = os.environ.get("CI", "").lower() in ("true", "1", "yes")
TQDM_KWARGS = dict(file=sys.stdout, dynamic_ncols=not CI, mininterval=5 if CI else 0.1)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

CACHE_DIR = ".cache"
EDHREC_CACHE_FILE = os.path.join(CACHE_DIR, "edhrec_inclusion_cache.json")
TAGGER_CACHE_FILE = os.path.join(CACHE_DIR, "tagger_tags_cache.json")

def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)

def load_json_cache(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json_cache(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def safe_get(url, params=None, headers=None, timeout=30, retries=5, pause_429=3.0, stream=False):
    merged_headers = dict(BROWSER_HEADERS)
    if headers:
        merged_headers.update(headers)
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=merged_headers, timeout=timeout, stream=stream)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(pause_429 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None

def get_image_url(card):
    if card.get("image_uris"):
        return card["image_uris"].get("normal")
    if card.get("card_faces"):
        for face in card["card_faces"]:
            if face.get("image_uris"):
                return face["image_uris"].get("normal")
    return None

def get_back_image_url(card, front_url=None):
    # Prefer explicit second-face image for transform/modal double-faced cards.
    faces = card.get("card_faces") or []
    if len(faces) >= 2:
        second_face = faces[1]
        image_uris = second_face.get("image_uris") or {}
        if image_uris.get("normal"):
            return image_uris.get("normal")

    # Fallback for legacy URLs where back art can be derived from front path.
    if front_url and "/front/" in front_url:
        return front_url.replace("/front/", "/back/")

    return None

def color_identity(card):
    colors = card.get("color_identity", [])
    order = ["W", "U", "B", "R", "G"]
    result = "".join(c for c in order if c in colors)
    return result if result else "COLORLESS"

def scryfall_search(query, max_cards):
    url = "https://api.scryfall.com/cards/search"
    params = {"q": query, "unique": "cards"}
    cards = []
    pbar = None
    while url and len(cards) < max_cards:
        r = safe_get(url, params=params, headers={"Accept": "application/json"})
        if not r:
            break
        data = r.json()
        page_cards = data.get("data", [])
        if pbar is None:
            total_cards = data.get("total_cards")
            total = min(total_cards, max_cards) if isinstance(total_cards, int) else max_cards
            pbar = tqdm(total=total, desc="Fetching from Scryfall search", unit="card", **TQDM_KWARGS)
        remaining = max_cards - len(cards)
        to_add = page_cards[:remaining]
        cards.extend(to_add)
        pbar.update(len(to_add))
        url = data.get("next_page")
        params = None
    if pbar is None:
        pbar = tqdm(total=0, desc="Fetching from Scryfall search", unit="card", **TQDM_KWARGS)
    pbar.close()
    return cards[:max_cards]

def download_json_stream(url):
    r = safe_get(url, headers={"Accept": "application/json"}, timeout=120, stream=True)
    if not r:
        raise RuntimeError(f"Could not download bulk JSON from {url}")
    total = int(r.headers.get("Content-Length", 0))
    chunks = []
    with tqdm(total=total if total > 0 else None, desc="Downloading Scryfall bulk JSON", unit="B", unit_scale=True, **TQDM_KWARGS) as pbar:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            pbar.update(len(chunk))
    raw = b"".join(chunks)
    return json.loads(raw.decode("utf-8"))

def card_matches_commander_paper(card):
    legalities = card.get("legalities") or {}
    games = card.get("games") or []
    return legalities.get("commander") == "legal" and "paper" in games

def scryfall_bulk_commander_paper(max_cards):
    bulk_index = safe_get("https://api.scryfall.com/bulk-data", headers={"Accept": "application/json"})
    if not bulk_index:
        raise RuntimeError("Could not fetch Scryfall bulk-data index")
    data = bulk_index.json().get("data", [])
    chosen = None
    for item in data:
        if item.get("type") == "default_cards":
            chosen = item
            break
    if not chosen or not chosen.get("download_uri"):
        raise RuntimeError("Could not find Scryfall default_cards bulk file")
    all_cards = download_json_stream(chosen["download_uri"])
    filtered = []
    with tqdm(total=len(all_cards), desc="Filtering bulk cards", unit="card", **TQDM_KWARGS) as pbar:
        for card in all_cards:
            pbar.update(1)
            if card_matches_commander_paper(card):
                filtered.append(card)
                if len(filtered) >= max_cards:
                    break
    return filtered

def get_inclusion(edhrec_url, edhrec_cache):
    if edhrec_url in edhrec_cache:
        return edhrec_cache[edhrec_url]
    r = safe_get(edhrec_url, headers={"User-Agent": "Mozilla/5.0"})
    if not r:
        edhrec_cache[edhrec_url] = None
        return None
    text = " ".join(BeautifulSoup(r.text, "html.parser").stripped_strings)
    m = re.search(r"(\d+(?:\.\d+)?)%\s*inclusion", text, re.IGNORECASE)
    value = float(m.group(1)) if m else None
    edhrec_cache[edhrec_url] = value
    return value

def _parse_tags_from_description(description_text):
    if not description_text:
        return []
    text = unescape(description_text)
    text = re.sub(r"\s+", " ", text).strip()
    m = re.search(r"Card Tags:\s*(.+?)(?:$|Art Tags:|Illustration Tags:)", text, re.IGNORECASE)
    if not m:
        return []
    segment = m.group(1).strip()
    parts = [p.strip(" •,;") for p in re.split(r"•|\||, (?=[a-zA-Z])", segment) if p.strip(" •,;")]
    cleaned = []
    seen = set()
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" •,;")
        low = p.lower()
        if p and low not in seen and not low.startswith("and "):
            seen.add(low)
            cleaned.append(p)
    return cleaned

def get_tagger_tags(card, tagger_cache):
    set_code = card.get("set")
    collector_number = card.get("collector_number")
    if not set_code or not collector_number:
        return []
    cache_key = f"{set_code}:{collector_number}"
    if cache_key in tagger_cache:
        return tagger_cache[cache_key]
    tagger_url = f"https://tagger.scryfall.com/card/{set_code}/{collector_number}"
    r = safe_get(tagger_url)
    if not r:
        tagger_cache[cache_key] = []
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    tags = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/tags/card/" in href:
            txt = unescape(a.get_text(" ", strip=True)).strip()
            if txt:
                tags.append(txt)
    if not tags:
        for meta in soup.find_all("meta"):
            content = meta.get("content")
            if content:
                parsed = _parse_tags_from_description(content)
                if parsed:
                    tags.extend(parsed)
    cleaned = []
    seen = set()
    for tag in tags:
        tag = re.sub(r"\s+", " ", tag).strip(" •,;")
        low = tag.lower()
        if tag and low not in seen:
            seen.add(low)
            cleaned.append(tag)
    tagger_cache[cache_key] = cleaned
    return cleaned

def fetch_cards(query, max_cards, use_bulk):
    if use_bulk:
        normalized_query = " ".join(query.lower().split())
        if normalized_query != "legal:commander game:paper":
            raise ValueError("--use-bulk only supports the exact query: legal:commander game:paper")
        return scryfall_bulk_commander_paper(max_cards)
    return scryfall_search(query, max_cards)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Full Scryfall query in quotes")
    parser.add_argument("--threshold", type=float, default=2.0, help="Max EDHREC inclusion percent")
    parser.add_argument("--max-cards", type=int, default=50000, help="Maximum number of Scryfall cards to fetch")
    parser.add_argument("--out", default="cards.json", help="Output JSON filename")
    parser.add_argument("--skip-tagger", action="store_true", help="Skip Scryfall Tagger tags for faster runs")
    parser.add_argument("--pretty", action="store_true", help="Write formatted JSON")
    parser.add_argument("--use-bulk", action="store_true", help="Use Scryfall bulk data instead of search API")
    parser.add_argument("--full-dataset", action="store_true", help="Keep all cards, even if include_pct is null or above threshold")
    args = parser.parse_args()

    ensure_cache_dir()
    edhrec_cache = load_json_cache(EDHREC_CACHE_FILE)
    tagger_cache = load_json_cache(TAGGER_CACHE_FILE)

    print("Starting Scryfall fetch...")
    cards = fetch_cards(args.query, args.max_cards, args.use_bulk)
    print(f"Fetched {len(cards)} cards from Scryfall")

    seen_oracle_ids = set()
    results = []

    total_cards = len(cards)
    edhrec_hits = 0
    tagger_hits = 0
    loop_start = time.time()
    print(f"Processing {total_cards} cards for EDHREC / Tagger...", flush=True)
    for idx, card in enumerate(tqdm(cards, desc="Processing cards", unit="card", **TQDM_KWARGS), start=1):
        oracle_id = card.get("oracle_id")
        if oracle_id in seen_oracle_ids:
            continue
        seen_oracle_ids.add(oracle_id)

        edhrec_url = card.get("related_uris", {}).get("edhrec")
        inclusion_pct = get_inclusion(edhrec_url, edhrec_cache) if edhrec_url else None
        if inclusion_pct is not None:
            edhrec_hits += 1

        if not args.full_dataset and (inclusion_pct is None or inclusion_pct >= args.threshold):
            continue

        tags = [] if args.skip_tagger else get_tagger_tags(card, tagger_cache)
        if tags:
            tagger_hits += 1

        front_image_url = get_image_url(card)
        back_image_url = get_back_image_url(card, front_image_url)

        results.append({
            "name": card.get("name"),
            "oracle_id": oracle_id,
            "scryfall_id": card.get("id"),
            "set": card.get("set"),
            "collector_number": card.get("collector_number"),
            "include_pct": inclusion_pct,
            "edhrec_found": inclusion_pct is not None,
            "card_type": card.get("type_line"),
            "mana_cost": card.get("mana_cost"),
            "cmc": card.get("cmc"),
            "edhrec_rank": card.get("edhrec_rank"),
            "edhrec_link": edhrec_url,
            "scryfall_link": card.get("scryfall_uri"),
            "image_url": front_image_url,
            "back_image_url": back_image_url,
            "color": color_identity(card),
            "color_identity": card.get("color_identity", []),
            "tags": tags,
            "keywords": card.get("keywords", []),
            "games": card.get("games", []),
            "legalities": card.get("legalities", {}),
        })

        if idx % 250 == 0:
            save_json_cache(EDHREC_CACHE_FILE, edhrec_cache)
            save_json_cache(TAGGER_CACHE_FILE, tagger_cache)

        if idx % 500 == 0 or idx == total_cards:
            elapsed = time.time() - loop_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (total_cards - idx) / rate if rate > 0 else 0
            print(
                f"[{idx}/{total_cards}] "
                f"EDHREC: {edhrec_hits} hits | "
                f"Tagger: {tagger_hits} with tags | "
                f"elapsed: {elapsed/60:.1f}m | ETA: {eta/60:.1f}m",
                flush=True,
            )

    results.sort(key=lambda x: ((x["include_pct"] is None), -(x["include_pct"] or -1), x["name"].lower()))

    payload = {
        "meta": {
            "query": args.query,
            "threshold": args.threshold,
            "max_cards": args.max_cards,
            "result_count": len(results),
            "generated_at_iso": datetime.now(timezone.utc).isoformat(),
            "generated_at_unix": int(time.time()),
            "includes_tagger_tags": not args.skip_tagger,
            "full_dataset": args.full_dataset,
            "used_bulk": args.use_bulk,
        },
        "cards": results,
    }

    print(f"Writing JSON with {len(results)} cards to {args.out}...")
    with open(args.out, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, f, ensure_ascii=False)

    save_json_cache(EDHREC_CACHE_FILE, edhrec_cache)
    save_json_cache(TAGGER_CACHE_FILE, tagger_cache)
    print("Done")

if __name__ == "__main__":
    main()
