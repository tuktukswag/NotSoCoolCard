from __future__ import annotations
import json, os, re
from functools import lru_cache
from pathlib import Path
from typing import Any
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
CARDS_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))
PRICES_FILE = Path(os.environ.get("CARDSITE_PRICES_JSON", BASE_DIR / "prices.json"))
app = Flask(__name__)

def load_json_file(path: Path, default):
    if not path.exists(): return default
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def load_cards_payload():
    if not CARDS_FILE.exists(): return {"meta": {"error": f"Missing JSON file: {CARDS_FILE.name}"}, "cards": []}
    data = load_json_file(CARDS_FILE, {"meta": {}, "cards": []})
    if isinstance(data, list): return {"meta": {}, "cards": data}
    if isinstance(data, dict) and "cards" in data:
        data.setdefault("meta", {})
        return data
    return {"meta": {}, "cards": []}

def load_prices_payload():
    data = load_json_file(PRICES_FILE, {"meta": {}, "prices": {}, "fx": {}})
    if isinstance(data, dict):
        data.setdefault("meta", {}); data.setdefault("prices", {}); data.setdefault("fx", {})
        return data
    return {"meta": {}, "prices": {}, "fx": {}}

def card_key(card):
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number: return f"{set_code}:{collector_number}"
    return str(card.get("oracle_id") or "")

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

def parse_plain_decklist(text: str):
    entries = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"): continue
        m = re.match(r"^\s*(\d+)\s*x?\s+(.+?)\s*$", line, flags=re.IGNORECASE)
        if not m: continue
        entries.append({"quantity": int(m.group(1)), "name": m.group(2).strip()})
    return entries

def extract_moxfield_id(url: str):
    m = re.search(r"moxfield\.com/decks/([A-Za-z0-9\-_]+)", url, flags=re.IGNORECASE)
    return m.group(1) if m else None

def extract_archidekt_id(url: str):
    m = re.search(r"archidekt\.com/decks/(\d+)", url, flags=re.IGNORECASE)
    return m.group(1) if m else None

def extract_card_entries_from_json(obj: Any, found):
    if isinstance(obj, dict):
        qty = None
        for key in ("quantity","qty","count"):
            if key in obj and isinstance(obj[key], int):
                qty = obj[key]; break
        possible_name = None
        if isinstance(obj.get("name"), str): possible_name = obj["name"]
        elif isinstance(obj.get("card"), dict) and isinstance(obj["card"].get("name"), str): possible_name = obj["card"]["name"]
        elif isinstance(obj.get("oracleCard"), dict) and isinstance(obj["oracleCard"].get("name"), str): possible_name = obj["oracleCard"]["name"]
        if qty and possible_name: found.append({"quantity": qty, "name": possible_name})
        for v in obj.values(): extract_card_entries_from_json(v, found)
    elif isinstance(obj, list):
        for i in obj: extract_card_entries_from_json(i, found)

def moxfield_from_html(url: str):
    r = safe_get(url)
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

def resolve_moxfield(url: str):
    deck_id = extract_moxfield_id(url)
    if not deck_id: return None
    for api_url in [f"https://api2.moxfield.com/v2/decks/all/{deck_id}", f"https://api2.moxfield.com/v2/decks/all/{deck_id}/export"]:
        r = safe_get(api_url, headers={"Accept": "application/json,text/plain;q=0.9,*/*;q=0.8"})
        if not r: continue
        if "application/json" in r.headers.get("Content-Type",""):
            try: data = r.json()
            except Exception: data = None
            if data is not None:
                found = []; extract_card_entries_from_json(data, found)
                if found: return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in found))
        else:
            parsed = parse_plain_decklist(r.text)
            if parsed: return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in parsed))
    html_found = moxfield_from_html(url)
    if html_found: return ("moxfield", "\n".join(f'{e["quantity"]} {e["name"]}' for e in html_found))
    return None

def resolve_archidekt(url: str):
    deck_id = extract_archidekt_id(url)
    if not deck_id: return None
    for api_url in [f"https://archidekt.com/api/decks/{deck_id}/", f"https://archidekt.com/api/decks/{deck_id}/small/"]:
        r = safe_get(api_url, headers={"Accept": "application/json,text/plain;q=0.9,*/*;q=0.8"})
        if not r: continue
        if "application/json" in r.headers.get("Content-Type",""):
            try: data = r.json()
            except Exception: continue
            found = []; extract_card_entries_from_json(data, found)
            if found: return ("archidekt", "\n".join(f'{e["quantity"]} {e["name"]}' for e in found))
    return None

def resolve_generic_html(url: str, source_name: str):
    r = safe_get(url)
    if not r: return None
    parsed = parse_plain_decklist("\n".join(BeautifulSoup(r.text, "html.parser").stripped_strings))
    if parsed: return (source_name, "\n".join(f'{e["quantity"]} {e["name"]}' for e in parsed))
    return None

def resolve_deck_url(url: str):
    lowered = url.lower().strip()
    if "moxfield.com/decks/" in lowered:
        result = resolve_moxfield(url)
        if result: return result
    if "archidekt.com/decks/" in lowered:
        result = resolve_archidekt(url)
        if result: return result
    if "manabox" in lowered:
        result = resolve_generic_html(url, "manabox")
        if result: return result
    return resolve_generic_html(url, "generic")

@lru_cache(maxsize=1)
def get_symbology_map():
    r = safe_get("https://api.scryfall.com/symbology", headers={"Accept": "application/json"})
    if not r: return {}
    try: data = r.json()
    except Exception: return {}
    return {item.get("symbol"): item.get("svg_uri") for item in data.get("data", []) if item.get("symbol") and item.get("svg_uri")}

@app.route("/")
def index(): return render_template("index.html", meta=merged_payload().get("meta", {}))

@app.route("/api/cards")
def api_cards(): return jsonify(merged_payload())

@app.route("/api/symbology")
def api_symbology(): return jsonify({"symbols": get_symbology_map()})

@app.route("/api/deck-resolve", methods=["POST"])
def api_deck_resolve():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url: return jsonify({"ok": False, "error": "Missing URL"}), 400
    resolved = resolve_deck_url(url)
    if not resolved: return jsonify({"ok": False, "error": "Could not read a decklist from that URL. Pasting a plain text decklist is the most reliable option."}), 400
    source_name, decklist = resolved
    return jsonify({"ok": True, "source": source_name, "decklist": decklist})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
