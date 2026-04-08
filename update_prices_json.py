"""

Script to update card prices and forex rates from Scryfall API and ECB.

Fetches prices for all cards in cards.json and saves to prices.json.

"""

from __future__ import annotations
import json, os, time, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import requests

# Base directory of the script
BASE_DIR = Path(__file__).resolve().parent

# Path to the cards JSON file, configurable via environment variable
CARDS_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))

# Path to the prices JSON file, configurable via environment variable
PRICES_FILE = Path(os.environ.get("CARDSITE_PRICES_JSON", BASE_DIR / "prices.json"))

# Sleep time between Scryfall API requests to avoid rate limiting
SCRYFALL_SLEEP = float(os.environ.get("SCRYFALL_SLEEP", "0.12"))

# Safe HTTP GET request with retries and rate limit handling
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

# Load cards data from JSON file
def load_cards():
    if not CARDS_FILE.exists():
        raise FileNotFoundError(f"Missing JSON file: {CARDS_FILE}")
    with open(CARDS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "cards" in data: return data["cards"]
    if isinstance(data, list): return data
    raise ValueError("Unexpected JSON structure in cards file")

# Generate a unique key for a card based on set and collector number, or oracle ID as fallback
def card_key(card: dict) -> str:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number: return f"{set_code}:{collector_number}"
    return str(card.get("oracle_id") or "")

# Fetch prices for a single card from Scryfall API - returns cheapest printing
def fetch_card_prices(card: dict):
    oracle_id = card.get("oracle_id")
    if not oracle_id: return None
    url = "https://api.scryfall.com/cards/search"
    params = {"q": f"oracle_id:{oracle_id}", "order": "released"}
    r = safe_get(url, params=params, headers={"Accept": "application/json"})
    if not r: return None
    data = r.json()
    cards_list = data.get("data", [])
    if not cards_list: return None
    
    # Find the cheapest printing by USD price
    cheapest = None
    cheapest_price = float('inf')
    for printing in cards_list:
        prices = printing.get("prices") or {}
        usd_price = prices.get("usd")
        if usd_price:
            try:
                usd_val = float(usd_price)
                if usd_val < cheapest_price:
                    cheapest_price = usd_val
                    cheapest = printing
            except (ValueError, TypeError):
                pass
    
    if not cheapest: return None
    prices = cheapest.get("prices") or {}
    return {
        "usd": prices.get("usd"),
        "usd_foil": prices.get("usd_foil"),
        "usd_etched": prices.get("usd_etched"),
        "eur": prices.get("eur"),
        "eur_foil": prices.get("eur_foil"),
        "eur_etched": prices.get("eur_etched"),
        "tix": prices.get("tix"),
    }

# Fetch USD to SEK exchange rate from ECB
def fetch_usd_sek_rate():
    # ECB daily reference rates XML: base EUR, includes USD and SEK.
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
        if currency == "USD": usd_rate = float(rate)
        if currency == "SEK": sek_rate = float(rate)
    if usd_rate and sek_rate:
        return sek_rate / usd_rate
    return None

# Main function to update prices for all cards
def main():
    cards = load_cards()
    print(f"Loaded {len(cards)} cards from {CARDS_FILE.name}")

    usd_sek = fetch_usd_sek_rate()
    if usd_sek is None:
        raise RuntimeError("Could not fetch USD/SEK exchange rate")

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

    payload = {
        "meta": {"updated_at": datetime.now(timezone.utc).isoformat(), "card_count": len(prices)},
        "fx": {"usd_sek": usd_sek, "updated_at": datetime.now(timezone.utc).isoformat()},
        "prices": prices
    }
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Done. Updated {updated} cards, skipped {skipped}. Wrote {PRICES_FILE.name}")

# Entry point to run the price update script
if __name__ == "__main__":
    main()
