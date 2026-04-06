from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

from flask import Flask, jsonify, render_template

try:
    import psycopg
except Exception:
    psycopg = None

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)


def load_cards() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {"meta": {"error": f"Missing JSON file: {DATA_FILE.name}"}, "cards": []}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return {"meta": {}, "cards": data}
    if isinstance(data, dict) and "cards" in data:
        data.setdefault("meta", {})
        return data

    return {"meta": {"warning": "Unexpected JSON structure."}, "cards": []}


def card_key(card: dict[str, Any]) -> str:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number:
        return f"{set_code}:{collector_number}"
    oracle_id = str(card.get("oracle_id") or "")
    return oracle_id


def load_prices_map() -> Dict[str, dict[str, Any]]:
    if not DATABASE_URL or psycopg is None:
        return {}

    query = """
        SELECT card_key, usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix, updated_at
        FROM card_prices
    """

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
    except Exception:
        return {}

    prices = {}
    for row in rows:
        prices[row[0]] = {
            "usd": row[1],
            "usd_foil": row[2],
            "usd_etched": row[3],
            "eur": row[4],
            "eur_foil": row[5],
            "eur_etched": row[6],
            "tix": row[7],
            "updated_at": row[8].isoformat() if row[8] else None,
        }
    return prices


def merged_payload() -> dict[str, Any]:
    data = load_cards()
    prices = load_prices_map()

    merged_cards = []
    for card in data.get("cards", []):
        merged = dict(card)
        merged["price"] = prices.get(card_key(card), {})
        merged_cards.append(merged)

    meta = dict(data.get("meta", {}))
    meta["prices_enabled"] = bool(DATABASE_URL and psycopg is not None)
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
