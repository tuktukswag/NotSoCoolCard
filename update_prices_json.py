"""

Script to update card prices and forex rates from Scryfall API and ECB.

Fetches prices for all cards in cards.json and saves to prices.json.

"""

from __future__ import annotations
import json, os, time, sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests

# Base directory of the script
BASE_DIR = Path(__file__).resolve().parent

# Path to the SQLite database file
DB_FILE = Path(os.environ.get("CARDSITE_DB", BASE_DIR / "cards.db"))

# Sleep time between Scryfall API requests to avoid rate limiting
SCRYFALL_SLEEP = float(os.environ.get("SCRYFALL_SLEEP", "0.12"))

# Generate a unique key for a card based on oracle ID
def card_key(card):
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
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Ensure oracle_id column exists
    try:
        cursor.execute('ALTER TABLE cards ADD COLUMN oracle_id TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Populate oracle_id if missing
    cursor.execute('SELECT id, name FROM cards WHERE oracle_id IS NULL')
    missing = cursor.fetchall()
    if missing:
        # Load from cards.json
        cards_file = BASE_DIR / "cards.json"
        if cards_file.exists():
            with open(cards_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            name_to_oracle = {card['name']: card.get('oracle_id') for card in data['cards']}
            for card_id, name in missing:
                oracle_id = name_to_oracle.get(name)
                if oracle_id:
                    cursor.execute('UPDATE cards SET oracle_id = ? WHERE id = ?', (oracle_id, card_id))
            conn.commit()
    
    # Load cards from DB
    cursor.execute('SELECT oracle_id, name FROM cards WHERE oracle_id IS NOT NULL')
    cards = [{'oracle_id': row[0], 'name': row[1]} for row in cursor.fetchall()]
    
    usd_sek = fetch_usd_sek_rate()
    if usd_sek is None:
        raise RuntimeError("Could not fetch USD/SEK exchange rate")

    updated = 0
    skipped = 0

    for idx, card in enumerate(cards, start=1):
        card_prices = fetch_card_prices(card)
        if not card_prices:
            skipped += 1; continue
        key = card_key(card)
        cursor.execute('''
        INSERT OR REPLACE INTO prices (key, usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            key,
            card_prices.get("usd"),
            card_prices.get("usd_foil"),
            card_prices.get("usd_etched"),
            card_prices.get("eur"),
            card_prices.get("eur_foil"),
            card_prices.get("eur_etched"),
            card_prices.get("tix")
        ))
        updated += 1
        if idx % 100 == 0: print(f"Processed {idx}/{len(cards)} cards...")
        time.sleep(SCRYFALL_SLEEP)

    # Update meta
    cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('usd_sek', str(usd_sek)))
    cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('updated_at', datetime.now(timezone.utc).isoformat()))
    cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ('card_count', str(len(cards))))
    
    conn.commit()
    conn.close()
    
    print(f"Done. Updated {updated} cards, skipped {skipped}. Updated DB")

# Entry point to run the price update script
if __name__ == "__main__":
    main()
