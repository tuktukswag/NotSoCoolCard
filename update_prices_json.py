from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
CARDS_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))
PRICES_FILE = Path(os.environ.get("CARDSITE_PRICES_JSON", BASE_DIR / "prices.json"))
SCRYFALL_SLEEP = float(os.environ.get("SCRYFALL_SLEEP", "0.12"))

def safe_get(url: str, params=None, headers=None, timeout: int = 30, retries: int = 4):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 404: return None
            if r.status_code == 429:
                time.sleep((attempt + 1) * 2); continue
            r.raise_for_status(); return r
        except requests.exceptions.RequestException:
            if attempt == retries - 1: return None
            time.sleep(1.5 * (attempt + 1))
    return None

def load_cards():
    if not CARDS_FILE.exists():
        raise FileNotFoundError(f"Missing JSON file: {CARDS_FILE}")
    with open(CARDS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "cards" in data: return data["cards"]
    if isinstance(data, list): return data
    raise ValueError("Unexpected JSON structure in cards file")

def card_key(card: dict) -> str:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number: return f"{set_code}:{collector_number}"
    return str(card.get("oracle_id") or "")

def fetch_card_prices(card: dict):
    set_code = card.get("set")
    collector_number = card.get("collector_number")
    if not set_code or not collector_number: return None
    url = f"https://api.scryfall.com/cards/{set_code}/{collector_number}"
    r = safe_get(url, headers={"Accept": "application/json"})
    if not r: return None
    data = r.json()
    prices = data.get("prices") or {}
    return {
        "usd": prices.get("usd"),
        "usd_foil": prices.get("usd_foil"),
        "usd_etched": prices.get("usd_etched"),
        "eur": prices.get("eur"),
        "eur_foil": prices.get("eur_foil"),
        "eur_etched": prices.get("eur_etched"),
        "tix": prices.get("tix"),
    }

def main():
    cards = load_cards()
    print(f"Loaded {len(cards)} cards from {CARDS_FILE.name}")
    prices = {}
    updated = 0
    skipped = 0
    for idx, card in enumerate(cards, start=1):
        card_prices = fetch_card_prices(card)
        if not card_prices:
            skipped += 1; continue
        prices[card_key(card)] = card_prices
        updated += 1
        if idx % 100 == 0: print(f"Processed {idx}/{len(cards)} cards...")
        time.sleep(SCRYFALL_SLEEP)
    payload = {"meta": {"updated_at": datetime.now(timezone.utc).isoformat(), "card_count": len(prices)}, "prices": prices}
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Done. Updated {updated} cards, skipped {skipped}. Wrote {PRICES_FILE.name}")

if __name__ == "__main__":
    main()
