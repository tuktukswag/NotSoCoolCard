#!/usr/bin/env python3
"""
One-command data refresh pipeline:
1) Fetch cards dataset from Scryfall + EDHREC using existing script.
2) Rebuild cards table in SQLite from cards.json.
3) Ensure oracle_id values are populated (legacy safety backfill).
4) Refresh prices (cheapest printing by oracle_id) and FX rate.

Usage:
  python update_all_data.py
  python update_all_data.py --skip-fetch
  python update_all_data.py --skip-tagger
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

from scryfall_bulk_cache import load_default_cards_bulk

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = Path(os.environ.get("CARDSITE_DB", BASE_DIR / "cards.db"))
CARDS_JSON = BASE_DIR / "cards.json"

DEFAULT_QUERY = "legal:commander game:paper"
DEFAULT_THRESHOLD = 2.0
DEFAULT_MAX_CARDS = 200000
DEFAULT_FETCH_SLEEP = 0.12
MAX_HTTP_RETRIES = 7

MELD_EXCLUDE_NAMES = {
    "Brisela, Voice of Nightmares",
    "Chittering Host",
    "Hanweir, the Writhing Township",
    "Mishra, Lost to Phyrexia",
    "Ragnarok, Divine Deliverance",
    "Titania, Gaea Incarnate",
    "Urza, Planeswalker",
}


def run_cards_fetch(skip_tagger: bool, skip_edhrec: bool, pretty: bool, max_cards: int = DEFAULT_MAX_CARDS, refresh_bulk: bool = False) -> None:
    cmd = [
        sys.executable,
        str(BASE_DIR / "scryfall_to_json_database_full_dataset.py"),
        DEFAULT_QUERY,
        "--threshold",
        str(DEFAULT_THRESHOLD),
        "--max-cards",
        str(max_cards),
        "--out",
        str(CARDS_JSON),
        "--use-bulk",
        "--full-dataset",
        "--edhrec-route-special-names",
    ]
    if refresh_bulk:
        cmd.append("--refresh-bulk")
    if skip_tagger:
        cmd.append("--skip-tagger")
    if skip_edhrec:
        cmd.append("--skip-edhrec")
    if pretty:
        cmd.append("--pretty")

    print("[1/4] Fetching cards dataset...")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


def create_tables(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY,
            oracle_id TEXT,
            name TEXT,
            card_type TEXT,
            oracle_text TEXT,
            mana_cost TEXT,
            back_mana_cost TEXT,
            cmc REAL,
            color TEXT,
            color_identity TEXT,
            include_pct REAL,
            tags TEXT,
            keywords TEXT,
            image_url TEXT,
            back_image_url TEXT,
            "set" TEXT,
            collector_number TEXT,
            all_sets TEXT
        )
        """
    )
    card_cols = {row[1] for row in cursor.execute('PRAGMA table_info(cards)').fetchall()}
    if "oracle_text" not in card_cols:
        cursor.execute('ALTER TABLE cards ADD COLUMN oracle_text TEXT')
    if "back_mana_cost" not in card_cols:
        cursor.execute('ALTER TABLE cards ADD COLUMN back_mana_cost TEXT')
    if "all_sets" not in card_cols:
        cursor.execute('ALTER TABLE cards ADD COLUMN all_sets TEXT')
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            key TEXT PRIMARY KEY,
            usd TEXT,
            usd_foil TEXT,
            usd_etched TEXT,
            eur TEXT,
            eur_foil TEXT,
            eur_etched TEXT,
            tix TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()


def build_all_sets_from_bulk() -> dict[str, list[str]]:
    """Read the Scryfall bulk cache and return a mapping of oracle_id -> [set_code, ...]."""
    bulk_path = BASE_DIR / ".cache" / "scryfall_default_cards.json"
    if not bulk_path.exists():
        return {}
    print("Building all_sets map from bulk cache...", flush=True)
    with bulk_path.open("r", encoding="utf-8") as f:
        bulk = json.load(f)
    oracle_to_sets: dict[str, list[str]] = {}
    for card in bulk:
        oracle_id = card.get("oracle_id")
        set_code = card.get("set")
        if not oracle_id or not set_code:
            continue
        if oracle_id not in oracle_to_sets:
            oracle_to_sets[oracle_id] = []
        if set_code not in oracle_to_sets[oracle_id]:
            oracle_to_sets[oracle_id].append(set_code)
    print(f"  {len(oracle_to_sets)} oracle IDs with set lists", flush=True)
    return oracle_to_sets


def normalize_back_images(cards: list[dict]) -> int:
    """Fill missing back_image_url for transform cards using legacy URL mapping."""
    updated = 0
    for card in cards:
        if card.get("back_image_url"):
            continue
        keywords = card.get("keywords") or []
        if "Transform" not in keywords:
            continue
        front_url = card.get("image_url")
        if isinstance(front_url, str) and "/front/" in front_url:
            card["back_image_url"] = front_url.replace("/front/", "/back/")
            updated += 1
    return updated


def rebuild_cards_table(cards_json_path: Path, db_path: Path, skip_tagger: bool = False, skip_edhrec: bool = False) -> int:
    if not cards_json_path.exists():
        raise FileNotFoundError(f"Missing cards dataset: {cards_json_path}")

    print("[2/4] Rebuilding cards table...")
    with cards_json_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    cards = payload.get("cards", [])
    sticker_before = len(cards)
    cards = [c for c in cards if "sticker" not in str(c.get("card_type") or "").lower()]
    removed_stickers = sticker_before - len(cards)
    if removed_stickers:
        print(f"Sticker filter: removed {removed_stickers} cards from cards.json payload")

    meld_before = len(cards)
    cards = [c for c in cards if str(c.get("name") or "") not in MELD_EXCLUDE_NAMES]
    removed_meld = meld_before - len(cards)
    if removed_meld:
        print(f"Meld hardcoded filter: removed {removed_meld} cards from cards.json payload")

    backfilled_back_images = normalize_back_images(cards)
    if backfilled_back_images:
        print(f"Back-image safety fill: {backfilled_back_images} cards")

    # Populate all_sets from bulk cache (covers cards.json built before this field existed)
    all_sets_map = build_all_sets_from_bulk()
    if all_sets_map:
        filled = 0
        for card in cards:
            if not card.get("all_sets"):
                oracle_id = card.get("oracle_id")
                if oracle_id and oracle_id in all_sets_map:
                    card["all_sets"] = all_sets_map[oracle_id]
                    filled += 1
        if filled:
            print(f"all_sets backfilled from bulk cache: {filled} cards")

    if removed_stickers or removed_meld or backfilled_back_images or (all_sets_map and filled):
        # Keep cards.json consistent with what is inserted into SQLite.
        payload["cards"] = cards
        with cards_json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    preserve_by_oracle: dict[str, tuple[float | None, list]] = {}
    try:
        cursor.execute("SELECT oracle_id, include_pct, tags FROM cards WHERE oracle_id IS NOT NULL AND oracle_id != ''")
        for oracle_id, include_pct, tags_json in cursor.fetchall():
            tags = []
            if tags_json:
                try:
                    parsed = json.loads(tags_json)
                    tags = parsed if isinstance(parsed, list) else []
                except Exception:
                    tags = []
            preserve_by_oracle[str(oracle_id)] = (include_pct, tags)
    except Exception:
        preserve_by_oracle = {}

    if preserve_by_oracle:
        for card in cards:
            oracle_id = str(card.get("oracle_id") or "")
            if not oracle_id:
                continue
            previous = preserve_by_oracle.get(oracle_id)
            if not previous:
                continue
            old_include, old_tags = previous
            # Always restore include_pct from DB if cards.json has null
            if card.get("include_pct") is None and old_include is not None:
                card["include_pct"] = old_include
            # Always restore tags from DB if cards.json has none
            if not card.get("tags") and old_tags:
                card["tags"] = old_tags

    cursor.execute("DELETE FROM cards")

    rows = []
    for card in cards:
        rows.append(
            (
                card.get("oracle_id"),
                card.get("name"),
                card.get("card_type"),
                card.get("oracle_text"),
                card.get("mana_cost"),
                card.get("back_mana_cost"),
                card.get("cmc"),
                card.get("color"),
                json.dumps(card.get("color_identity", [])),
                card.get("include_pct"),
                json.dumps(card.get("tags", [])),
                json.dumps(card.get("keywords", [])),
                card.get("image_url"),
                card.get("back_image_url"),
                card.get("set"),
                card.get("collector_number"),
                json.dumps(card.get("all_sets", [])),
            )
        )

    cursor.executemany(
        """
        INSERT INTO cards (
            oracle_id, name, card_type, oracle_text, mana_cost, back_mana_cost, cmc, color,
            color_identity, include_pct, tags, keywords, image_url,
            back_image_url, "set", collector_number, all_sets
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    print(f"Cards table refreshed with {len(rows)} rows")
    return len(rows)


def safe_get(url: str, **kwargs):
    request_label = kwargs.pop("request_label", None)
    retry_delay = 1.5
    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        try:
            r = requests.get(url, timeout=20, **kwargs)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else retry_delay
                if request_label:
                    print(f"  {request_label}: rate limited, retry {attempt}/{MAX_HTTP_RETRIES} in {delay:.1f}s", flush=True)
                time.sleep(delay)
                retry_delay = min(retry_delay * 1.8, 45)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if request_label:
                print(f"  {request_label}: retry {attempt}/{MAX_HTTP_RETRIES} after {type(exc).__name__} in {retry_delay:.1f}s", flush=True)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.8, 45)
    return None


def ensure_oracle_ids(db_path: Path, cards_json_path: Path, sleep_seconds: float) -> int:
    """Safety backfill for legacy/malformed rows with missing oracle_id."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM cards WHERE oracle_id IS NULL OR oracle_id = ''")
    missing_rows = cursor.fetchall()
    if not missing_rows:
        conn.close()
        return 0

    print(f"[3/4] Backfilling oracle_id for {len(missing_rows)} rows...")

    name_to_oracle = {}
    if cards_json_path.exists():
        with cards_json_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        for card in payload.get("cards", []):
            name = card.get("name")
            oracle_id = card.get("oracle_id")
            if name and oracle_id and name not in name_to_oracle:
                name_to_oracle[name] = oracle_id

    fixed = 0
    still_missing = []
    for card_id, name in missing_rows:
        oracle_id = name_to_oracle.get(name)
        if oracle_id:
            cursor.execute("UPDATE cards SET oracle_id = ? WHERE id = ?", (oracle_id, card_id))
            fixed += 1
        else:
            still_missing.append((card_id, name))

    conn.commit()

    # Fallback to Scryfall exact name lookup if anything remains missing.
    for idx, (card_id, name) in enumerate(still_missing, start=1):
        r = safe_get(
            "https://api.scryfall.com/cards/named",
            params={"exact": name},
            headers={"Accept": "application/json"},
        )
        if r is None:
            continue
        data = r.json()
        oracle_id = data.get("oracle_id")
        if oracle_id:
            cursor.execute("UPDATE cards SET oracle_id = ? WHERE id = ?", (oracle_id, card_id))
            fixed += 1
        if idx % 50 == 0:
            conn.commit()
            print(f"oracle backfill progress: {idx}/{len(still_missing)}")
        time.sleep(sleep_seconds)

    conn.commit()
    conn.close()
    return fixed


def fetch_usd_sek_rate() -> float | None:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    r = safe_get(url, headers={"Accept": "application/xml,text/xml"})
    if not r:
        return None

    root = ET.fromstring(r.text)
    usd_rate = None
    sek_rate = None
    for elem in root.iter():
        currency = elem.attrib.get("currency")
        rate = elem.attrib.get("rate")
        if not currency or not rate:
            continue
        if currency == "USD":
            usd_rate = float(rate)
        elif currency == "SEK":
            sek_rate = float(rate)

    if usd_rate and sek_rate:
        return sek_rate / usd_rate
    return None


def fetch_bulk_prices_by_oracle_id(refresh_bulk: bool = False) -> dict:
    """Download Scryfall default_cards bulk data and return cheapest price per oracle_id."""
    CI = os.environ.get("CI", "").lower() in ("true", "1", "yes")
    print("  Loading Scryfall bulk data for prices...", flush=True)
    try:
        all_cards = load_default_cards_bulk(
            base_dir=BASE_DIR,
            safe_get=safe_get,
            tqdm_kwargs=dict(file=sys.stdout, dynamic_ncols=not CI, mininterval=5 if CI else 0.1),
            force_refresh=refresh_bulk,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"bulk not available, cant fetch prices ({exc})") from exc

    # Group by oracle_id, keep cheapest USD printing's full price block
    best: dict[str, tuple[float, dict]] = {}  # oracle_id -> (cheapest_usd, prices_dict)
    print(f"  Building price map from {len(all_cards)} printings...", flush=True)
    for card in tqdm(all_cards, desc="Indexing prices", unit="card", file=sys.stdout,
                     dynamic_ncols=not CI, mininterval=5 if CI else 0.1):
        if card.get("oversized"):
            continue
        oid = card.get("oracle_id")
        if not oid:
            continue
        prices = card.get("prices") or {}
        usd = prices.get("usd")
        if not usd:
            continue
        try:
            usd_val = float(usd)
        except (ValueError, TypeError):
            continue
        if oid not in best or usd_val < best[oid][0]:
            best[oid] = (usd_val, prices)
    return {oid: data[1] for oid, data in best.items()}


def rebuild_prices(db_path: Path, refresh_bulk: bool = False) -> tuple[int, int, int]:
    print("[4/4] Rebuilding prices table...")
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM prices")

    cursor.execute("SELECT DISTINCT oracle_id FROM cards WHERE oracle_id IS NOT NULL AND oracle_id != ''")
    oracle_ids = [row[0] for row in cursor.fetchall()]

    price_map = fetch_bulk_prices_by_oracle_id(refresh_bulk=refresh_bulk)

    updated = 0
    skipped = 0
    CI = os.environ.get("CI", "").lower() in ("true", "1", "yes")
    for oracle_id in tqdm(oracle_ids, desc="Prices", unit="card", file=sys.stdout, dynamic_ncols=not CI, mininterval=5 if CI else 0.1):
        prices = price_map.get(oracle_id)
        if not prices:
            skipped += 1
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO prices (key, usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oracle_id,
                prices.get("usd"),
                prices.get("usd_foil"),
                prices.get("usd_etched"),
                prices.get("eur"),
                prices.get("eur_foil"),
                prices.get("eur_etched"),
                prices.get("tix"),
            ),
        )
        updated += 1

    fx_rate = fetch_usd_sek_rate()
    if fx_rate is not None:
        cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ("usd_sek", str(fx_rate)))

    cursor.execute(
        'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
        ("updated_at", datetime.now(timezone.utc).isoformat()),
    )
    cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ("card_count", str(len(oracle_ids))))

    conn.commit()
    conn.close()
    return len(oracle_ids), updated, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end cards.db refresh")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip cards.json fetch and reuse existing cards.json")
    parser.add_argument("--skip-tagger", action="store_true", help="Skip tagger tags during card fetch")
    parser.add_argument("--skip-edhrec", action="store_true", help="Skip EDHREC inclusion lookup during card fetch")
    parser.add_argument("--skip-prices", action="store_true", help="Skip price update and keep existing prices")
    parser.add_argument("--pretty", action="store_true", help="Write pretty cards.json during card fetch")
    parser.add_argument("--max-cards", type=int, default=DEFAULT_MAX_CARDS, help=f"Max cards to fetch from Scryfall (default: {DEFAULT_MAX_CARDS})")
    parser.add_argument("--refresh-bulk", action="store_true", help="Force a fresh Scryfall bulk download before using cached bulk data")
    parser.add_argument("--oracle-sleep", type=float, default=DEFAULT_FETCH_SLEEP, help="Delay between fallback oracle lookup requests")
    args = parser.parse_args()

    started = time.time()

    if not args.skip_fetch:
        run_cards_fetch(skip_tagger=args.skip_tagger, skip_edhrec=args.skip_edhrec, pretty=args.pretty, max_cards=args.max_cards, refresh_bulk=args.refresh_bulk)
    else:
        print("[1/4] Skipped cards fetch (--skip-fetch)")

    card_rows = rebuild_cards_table(CARDS_JSON, DB_FILE, skip_tagger=args.skip_tagger, skip_edhrec=args.skip_edhrec)
    backfilled = ensure_oracle_ids(DB_FILE, CARDS_JSON, args.oracle_sleep)
    if not args.skip_prices:
        try:
            total_oracle, updated, skipped = rebuild_prices(DB_FILE, refresh_bulk=args.refresh_bulk)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        print("[3/4] Skipped price update (--skip-prices)")
        total_oracle = updated = skipped = 0

    elapsed = time.time() - started
    print("\nRefresh complete")
    print(f"cards rows: {card_rows}")
    print(f"oracle backfilled: {backfilled}")
    if not args.skip_prices:
        print(f"price targets: {total_oracle}, updated: {updated}, skipped: {skipped}")
    print(f"elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
