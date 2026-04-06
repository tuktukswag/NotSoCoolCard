from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
import psycopg

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(os.environ.get("CARDSITE_JSON", BASE_DIR / "cards.json"))
DATABASE_URL = os.environ.get("DATABASE_URL")
SCRYFALL_SLEEP = float(os.environ.get("SCRYFALL_SLEEP", "0.12"))


def safe_get(url: str, params=None, headers=None, timeout: int = 30, retries: int = 4):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep((attempt + 1) * 2)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def load_cards():
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Missing JSON file: {DATA_FILE}")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "cards" in data:
        return data["cards"]
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected JSON structure in cards file")


def card_key(card: dict) -> str:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").lower()
    if set_code and collector_number:
        return f"{set_code}:{collector_number}"
    oracle_id = str(card.get("oracle_id") or "")
    return oracle_id


def create_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS card_prices (
                card_key TEXT PRIMARY KEY,
                oracle_id TEXT,
                set_code TEXT,
                collector_number TEXT,
                name TEXT,
                usd TEXT,
                usd_foil TEXT,
                usd_etched TEXT,
                eur TEXT,
                eur_foil TEXT,
                eur_etched TEXT,
                tix TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def fetch_card_prices(card: dict):
    set_code = card.get("set")
    collector_number = card.get("collector_number")
    if not set_code or not collector_number:
        return None

    url = f"https://api.scryfall.com/cards/{set_code}/{collector_number}"
    r = safe_get(url, headers={"Accept": "application/json"})
    if not r:
        return None

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


def upsert_price(conn, card: dict, prices: dict):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO card_prices (
                card_key, oracle_id, set_code, collector_number, name,
                usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (card_key) DO UPDATE SET
                oracle_id = EXCLUDED.oracle_id,
                set_code = EXCLUDED.set_code,
                collector_number = EXCLUDED.collector_number,
                name = EXCLUDED.name,
                usd = EXCLUDED.usd,
                usd_foil = EXCLUDED.usd_foil,
                usd_etched = EXCLUDED.usd_etched,
                eur = EXCLUDED.eur,
                eur_foil = EXCLUDED.eur_foil,
                eur_etched = EXCLUDED.eur_etched,
                tix = EXCLUDED.tix,
                updated_at = NOW()
        """, (
            card_key(card),
            card.get("oracle_id"),
            card.get("set"),
            str(card.get("collector_number") or ""),
            card.get("name"),
            prices.get("usd"),
            prices.get("usd_foil"),
            prices.get("usd_etched"),
            prices.get("eur"),
            prices.get("eur_foil"),
            prices.get("eur_etched"),
            prices.get("tix"),
        ))


def main():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")

    cards = load_cards()
    print(f"Loaded {len(cards)} cards from {DATA_FILE.name}")

    with psycopg.connect(DATABASE_URL) as conn:
        create_table(conn)

        updated = 0
        skipped = 0

        for idx, card in enumerate(cards, start=1):
            prices = fetch_card_prices(card)
            if not prices:
                skipped += 1
                continue

            upsert_price(conn, card, prices)
            updated += 1

            if idx % 100 == 0:
                conn.commit()
                print(f"Processed {idx}/{len(cards)} cards...")

            time.sleep(SCRYFALL_SLEEP)

        conn.commit()

    print(f"Done. Updated {updated} cards, skipped {skipped}.")


if __name__ == "__main__":
    main()
