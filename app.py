"""

NotSoCoolCard - A web application for searching and validating Magic: The Gathering Commander cards.

This Flask app serves a frontend for card search and deck checking, using data from JSON files.

"""

from __future__ import annotations
import json, logging, os, re
from functools import lru_cache
from pathlib import Path
from typing import Any
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent

# Path to the cards JSON file, configurable via environment variable
CARDS_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))

# Path to the prices JSON file, configurable via environment variable
PRICES_FILE = Path(os.environ.get("CARDSITE_PRICES_JSON", BASE_DIR / "prices.json"))

# Initialize Flask application
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

# Helper function to load JSON from file, returning default if file doesn't exist
def load_json_file(path: Path, default):
    if not path.exists(): return default
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

# Load and validate the cards data from JSON file
def load_cards_payload():
    if not CARDS_FILE.exists(): return {"meta": {"error": f"Missing JSON file: {CARDS_FILE.name}"}, "cards": []}
    data = load_json_file(CARDS_FILE, {"meta": {}, "cards": []})
    if isinstance(data, list): return {"meta": {}, "cards": data}
    if isinstance(data, dict) and "cards" in data:
        data.setdefault("meta", {})
        return data
    return {"meta": {}, "cards": []}

# Load and validate the prices data from JSON file
def load_prices_payload():
    data = load_json_file(PRICES_FILE, {"meta": {}, "prices": {}, "fx": {}})
    if isinstance(data, dict):
        data.setdefault("meta", {}); data.setdefault("prices", {}); data.setdefault("fx", {})
        return data
    return {"meta": {}, "prices": {}, "fx": {}}

# Generate a unique key for a card based on set and collector number, or oracle ID as fallback
def card_key(card):
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number: return f"{set_code}:{collector_number}"
    return str(card.get("oracle_id") or "")

# Merge cards data with prices and forex rates
def merged_payload():
    cards_payload = load_cards_payload()
    prices_payload = load_prices_payload()
    prices_map = prices_payload.get("prices", {})
    fx = prices_payload.get("fx", {})
    merged_cards = []
    for card in cards_payload.get("cards", []):
        merged = dict(card); merged["price"] = prices_map.get(card_key(card), {}); merged_cards.append(merged)
    meta = dict(cards_payload.get("meta", {}))
    meta["usd_sek_rate"] = fx.get("usd_sek")
    return {"meta": meta, "cards": merged_cards}

# Safe HTTP GET request with retries and rate limit handling
def safe_get(url: str, headers=None, timeout: int = 30):
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; Cardsite/1.0)", "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.8"}
    if headers: hdrs.update(headers)
    for _ in range(4):
        try:
            r = requests.get(url, headers=hdrs, timeout=timeout)
            if r.status_code == 404: return None
            if r.status_code == 429: continue
            r.raise_for_status(); return r
        except requests.exceptions.RequestException:
            continue
    return None

# Parse a plain text decklist into card entries with quantities and names
def parse_plain_decklist(text: str):
    entries = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"): continue
        m = re.match(r"^\s*(\d+)\s*x?\s+(.+?)\s*$", line, flags=re.IGNORECASE)
        if not m: continue
        entries.append({"quantity": int(m.group(1)), "name": m.group(2).strip()})
    return entries

# Extract deck ID from Moxfield URL
def extract_moxfield_id(url: str):
    m = re.search(r"moxfield\.com/decks/([A-Za-z0-9\-_]+)", url, flags=re.IGNORECASE)
    return m.group(1) if m else None

# Extract deck ID from Archidekt URL
def extract_archidekt_id(url: str):
    m = re.search(r"archidekt\.com/decks/(\d+)", url, flags=re.IGNORECASE)
    return m.group(1) if m else None

# Recursively extract card entries from JSON data structures
def extract_card_entries_from_json(obj: Any, found):
    if isinstance(obj, dict):
        qty = None
        for key in ("quantity","qty","count"):
            if key in obj and isinstance(obj[key], int):
                qty = obj[key]; break
        possible_name = None
        if isinstance(obj.get("name"), str):
            possible_name = obj["name"]
        elif isinstance(obj.get("card"), dict):
            card_obj = obj["card"]
            if isinstance(card_obj.get("name"), str):
                possible_name = card_obj["name"]
            elif isinstance(card_obj.get("displayName"), str):
                possible_name = card_obj["displayName"]
            elif isinstance(card_obj.get("oracleCard"), dict) and isinstance(card_obj["oracleCard"].get("name"), str):
                possible_name = card_obj["oracleCard"]["name"]
        elif isinstance(obj.get("oracleCard"), dict) and isinstance(obj["oracleCard"].get("name"), str):
            possible_name = obj["oracleCard"]["name"]
        if qty and possible_name: found.append({"quantity": qty, "name": possible_name})
        for v in obj.values(): extract_card_entries_from_json(v, found)
    elif isinstance(obj, list):
        for i in obj: extract_card_entries_from_json(i, found)

# Extract decklist from Moxfield HTML page
def moxfield_from_html(url: str, headers=None):
    r = safe_get(url, headers=headers)
    if not r: return None
    parsed = parse_plain_decklist("\n".join(BeautifulSoup(r.text, "html.parser").stripped_strings))
    if parsed: return parsed
    for blob in re.findall(r'<script[^>]*>(.*?)</script>', r.text, flags=re.DOTALL | re.IGNORECASE):
        if "mainboard" not in blob and "boards" not in blob and "commanders" not in blob: continue
        try:
            start = blob.find("{"); end = blob.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(blob[start:end+1]); found = []; extract_card_entries_from_json(data, found)
                if found: return found
        except Exception:
            pass
    return None

# Resolve decklist from Moxfield URL using API or HTML parsing
def resolve_moxfield(url: str):
    deck_id = extract_moxfield_id(url)
    print(f"Moxfield: extracted deck_id {deck_id}")
    if not deck_id: return None
    mox_headers = {
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://moxfield.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Connection": "keep-alive",
    }
    for api_url in [f"https://api.moxfield.com/v2/decks/all/{deck_id}", f"https://api.moxfield.com/v2/decks/all/{deck_id}/export"]:
        print(f"Moxfield: trying {api_url}")
        r = safe_get(api_url, headers=mox_headers)
        if not r:
            print(f"Moxfield: no response from {api_url}")
            continue
        print(f"Moxfield: got response from {api_url}")
        if "application/json" in r.headers.get("Content-Type",""):
            try: data = r.json()
            except Exception: data = None
            if data is not None:
                found = []; extract_card_entries_from_json(data, found)
                if found:
                    print(f"Moxfield: extracted {len(found)} cards from JSON")
                    return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in found))
        else:
            parsed = parse_plain_decklist(r.text)
            if parsed:
                print(f"Moxfield: parsed {len(parsed)} cards from plain text")
                return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in parsed))
    print("Moxfield: trying HTML scraping")
    html_found = moxfield_from_html(url, headers=mox_headers)
    if html_found:
        print(f"Moxfield: extracted {len(html_found)} cards from HTML")
        return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in html_found))
    print("Moxfield: failed to extract decklist")
    return None

# Resolve decklist from Archidekt URL using API
def resolve_archidekt(url: str):
    deck_id = extract_archidekt_id(url)
    print(f"Archidekt: extracted deck_id {deck_id}")
    if not deck_id: return None
    for api_url in [f"https://archidekt.com/api/decks/{deck_id}/", f"https://archidekt.com/api/decks/{deck_id}/small/"]:
        print(f"Archidekt: trying {api_url}")
        r = safe_get(api_url, headers={"Accept": "application/json,text/plain;q=0.9,*/*;q=0.8"})
        if not r:
            print(f"Archidekt: no response from {api_url}")
            continue
        print(f"Archidekt: got response from {api_url}")
        if "application/json" in r.headers.get("Content-Type",""):
            try: data = r.json()
            except Exception: 
                print("Archidekt: failed to parse JSON")
                continue
            # Exclude maybeboard and considering sections
            if "maybeboard" in data:
                del data["maybeboard"]
            if "considering" in data:
                del data["considering"]
            found = []; extract_card_entries_from_json(data, found)
            if found:
                print(f"Archidekt: extracted {len(found)} cards from JSON")
                return ("archidekt", "\n".join(f'{e["quantity"]} {e["name"]}' for e in found))
    print("Archidekt: failed to extract decklist")
    return None

# Resolve decklist from generic HTML page by parsing text
def resolve_generic_html(url: str, source_name: str):
    r = safe_get(url)
    if not r: return None
    parsed = parse_plain_decklist("\n".join(BeautifulSoup(r.text, "html.parser").stripped_strings))
    if parsed: return (source_name, "\n".join(f'{e["quantity"]} {e["name"]}' for e in parsed))
    return None

# Main function to resolve decklist from various URL types
def resolve_deck_url(url: str):
    lowered = url.lower().strip()
    print(f"Resolving deck URL: {url}")
    if "moxfield.com/decks/" in lowered:
        print("Detected Moxfield URL")
        result = resolve_moxfield(url)
        if result: return result
    if "archidekt.com/decks/" in lowered:
        print("Detected Archidekt URL")
        result = resolve_archidekt(url)
        if result: return result
    if "manabox" in lowered:
        print("Detected Manabox URL")
        result = resolve_generic_html(url, "manabox")
        if result: return result
    print("Falling back to generic HTML parsing")
    return resolve_generic_html(url, "generic")

# Cached function to fetch mana symbol SVG URIs from Scryfall API
@lru_cache(maxsize=1)
def get_symbology_map():
    r = safe_get("https://api.scryfall.com/symbology", headers={"Accept": "application/json"})
    if not r: return {}
    try: data = r.json()
    except Exception: return {}
    return {item.get("symbol"): item.get("svg_uri") for item in data.get("data", []) if item.get("symbol") and item.get("svg_uri")}

# Route for the main index page
@app.route("/")
def index(): return render_template("index.html", meta=merged_payload().get("meta", {}))

# API route to get merged cards and prices data
@app.route("/api/cards")
def api_cards(): return jsonify(merged_payload())

# API route to get mana symbol SVG URIs
@app.route("/api/symbology")
def api_symbology(): return jsonify({"symbols": get_symbology_map()})

# API route to resolve decklist from URL
@app.route("/api/deck-resolve", methods=["POST"])
def api_deck_resolve():
    raw_body = request.get_data(as_text=True)
    print(f"api_deck_resolve: raw_body={raw_body!r}")
    print(f"api_deck_resolve: content-type={request.headers.get('Content-Type')}")
    data = request.get_json(silent=True)
    if data is None:
        try:
            data = json.loads(raw_body or "{}")
            print(f"api_deck_resolve: parsed raw JSON data={data}")
        except Exception as exc:
            print(f"api_deck_resolve: failed to parse JSON body: {exc}")
            data = {}
    else:
        print(f"api_deck_resolve: received data={data}")

    url = (data.get("url") or "").strip()
    if not url:
        print("api_deck_resolve: missing URL")
        return jsonify({"ok": False, "error": "Missing URL"}), 400

    resolved = resolve_deck_url(url)
    if not resolved:
        print("api_deck_resolve: resolve_deck_url failed")
        error_msg = "Could not read a decklist from that URL. Pasting a plain text decklist is the most reliable option."
        if "moxfield.com/decks/" in lowered:
            error_msg += " Moxfield may be blocking automated requests; try pasting the decklist manually."
        return jsonify({"ok": False, "error": error_msg}), 400

    source_name, decklist = resolved
    print(f"api_deck_resolve: success from {source_name}")
    return jsonify({"ok": True, "source": source_name, "decklist": decklist})

# Main entry point to run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
