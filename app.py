from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from flask import Flask, jsonify, render_template

BASE_DIR = Path(__file__).resolve().parent
CARDS_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))
PRICES_FILE = Path(os.environ.get("CARDSITE_PRICES_JSON", BASE_DIR / "prices.json"))
app = Flask(__name__)

def load_json_file(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_cards_payload() -> dict[str, Any]:
    if not CARDS_FILE.exists():
        return {"meta": {"error": f"Missing JSON file: {CARDS_FILE.name}"}, "cards": []}
    data = load_json_file(CARDS_FILE, {"meta": {}, "cards": []})
    if isinstance(data, list):
        return {"meta": {}, "cards": data}
    if isinstance(data, dict) and "cards" in data:
        data.setdefault("meta", {})
        return data
    return {"meta": {"warning": "Unexpected cards JSON structure."}, "cards": []}

def load_prices_payload() -> dict[str, Any]:
    data = load_json_file(PRICES_FILE, {"meta": {}, "prices": {}, "fx": {}})
    if isinstance(data, dict):
        data.setdefault("meta", {})
        data.setdefault("prices", {})
        data.setdefault("fx", {})
        return data
    return {"meta": {"warning": "Unexpected prices JSON structure."}, "prices": {}, "fx": {}}

def card_key(card: dict[str, Any]) -> str:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number:
        return f"{set_code}:{collector_number}"
    return str(card.get("oracle_id") or "")

def merged_payload() -> dict[str, Any]:
    cards_payload = load_cards_payload()
    prices_payload = load_prices_payload()
    prices_map = prices_payload.get("prices", {})
    fx = prices_payload.get("fx", {})

    merged_cards = []
    for card in cards_payload.get("cards", []):
        merged = dict(card)
        merged["price"] = prices_map.get(card_key(card), {})
        merged_cards.append(merged)

    meta = dict(cards_payload.get("meta", {}))
    meta["prices_enabled"] = bool(prices_map)
    meta["prices_updated_at"] = prices_payload.get("meta", {}).get("updated_at")
    meta["usd_sek_rate"] = fx.get("usd_sek")
    meta["fx_updated_at"] = fx.get("updated_at")
    return {"meta": meta, "cards": merged_cards}

@app.route("/")
def index():
    payload = merged_payload()
    return render_template("index.html", meta=payload.get("meta", {}))

@app.route("/api/cards")
def api_cards():
    return jsonify(merged_payload())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
