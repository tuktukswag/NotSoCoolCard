#!/usr/bin/env python3
"""
Migrate cards.db to populate oracle_id, set, and collector_number from Scryfall API.
"""

import sqlite3
import requests
import time
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "cards.db"

def fetch_scryfall_card(name):
    """Fetch card details from Scryfall by exact name."""
    url = "https://api.scryfall.com/cards/named"
    params = {"exact": name}
    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        return {
            "oracle_id": data.get("oracle_id"),
            "set": data.get("set"),
            "collector_number": data.get("collector_number"),
        }
    except Exception as e:
        print(f"Error fetching {name}: {e}")
        return None

def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE cards ADD COLUMN set TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE cards ADD COLUMN collector_number TEXT')
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    
    # Get all cards with missing oracle_id
    cursor.execute('SELECT id, name FROM cards WHERE oracle_id IS NULL ORDER BY id')
    cards_to_fetch = cursor.fetchall()
    
    if not cards_to_fetch:
        print("All cards already have oracle_id!")
        conn.close()
        return
    
    print(f"Fetching {len(cards_to_fetch)} cards from Scryfall...")
    
    fetched = 0
    not_found = 0
    
    for idx, (card_id, name) in enumerate(cards_to_fetch, 1):
        data = fetch_scryfall_card(name)
        if data:
            cursor.execute(
                'UPDATE cards SET oracle_id = ?, set = ?, collector_number = ? WHERE id = ?',
                (data["oracle_id"], data["set"], data["collector_number"], card_id)
            )
            fetched += 1
            if idx % 50 == 0:
                print(f"[{idx}/{len(cards_to_fetch)}] Progress: {fetched} fetched, {not_found} not found")
        else:
            not_found += 1
        
        if idx % 20 == 0:
            conn.commit()
        time.sleep(0.05)  # Rate limit ~20 req/sec
    
    conn.commit()
    conn.close()
    print(f"Done! Fetched: {fetched}, Not found: {not_found}, Total: {len(cards_to_fetch)}")

if __name__ == "__main__":
    main()
