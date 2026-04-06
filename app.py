from __future__ import annotations

import json
import os
from pathlib import Path
from flask import Flask, jsonify, render_template

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))

app = Flask(__name__)


def load_cards():
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


@app.route("/")
def index():
    data = load_cards()
    return render_template("index.html", meta=data.get("meta", {}))


@app.route("/api/cards")
def api_cards():
    return jsonify(load_cards())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
