#!/usr/bin/env python3
"""
One-command data refresh pipeline:
1) Fetch cards dataset from Scryfall + EDHREC using existing script.
2) Rebuild cards table in SQLite from cards.json.
3) Ensure oracle_id values are populated (legacy safety backfill).
4) Refresh prices (cheapest printing by oracle_id) and FX rate.

Usage:
  python update_all_data.py
  python update_all_data.py --skip-fetch
  python update_all_data.py --skip-tagger
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = Path(os.environ.get("CARDSITE_DB", BASE_DIR / "cards.db"))
CARDS_JSON = BASE_DIR / "cards.json"

DEFAULT_QUERY = "legal:commander game:paper"
DEFAULT_THRESHOLD = 2.0
DEFAULT_MAX_CARDS = 200000
DEFAULT_FETCH_SLEEP = 0.12
DEFAULT_PRICE_SLEEP = 0.12
MAX_HTTP_RETRIES = 7


def run_cards_fetch(skip_tagger: bool, pretty: bool) -> None:
    cmd = [
        sys.executable,
        str(BASE_DIR / "scryfall_to_json_database_full_dataset.py"),
        DEFAULT_QUERY,
        "--threshold",
        str(DEFAULT_THRESHOLD),
        "--max-cards",
        str(DEFAULT_MAX_CARDS),
        "--out",
        str(CARDS_JSON),
        "--use-bulk",
        "--full-dataset",
    ]
    if skip_tagger:
        cmd.append("--skip-tagger")
    if pretty:
        cmd.append("--pretty")

    print("[1/4] Fetching cards dataset...")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


def create_tables(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY,
            oracle_id TEXT,
            name TEXT,
            card_type TEXT,
            mana_cost TEXT,
            cmc REAL,
            color TEXT,
            color_identity TEXT,
            include_pct REAL,
            tags TEXT,
            keywords TEXT,
            image_url TEXT,
            back_image_url TEXT,
            "set" TEXT,
            collector_number TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            key TEXT PRIMARY KEY,
            usd TEXT,
            usd_foil TEXT,
            usd_etched TEXT,
            eur TEXT,
            eur_foil TEXT,
            eur_etched TEXT,
            tix TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()


def normalize_back_images(cards: list[dict]) -> int:
    """Fill missing back_image_url for transform cards using legacy URL mapping."""
    updated = 0
    for card in cards:
        if card.get("back_image_url"):
            continue
        keywords = card.get("keywords") or []
        if "Transform" not in keywords:
            continue
        front_url = card.get("image_url")
        if isinstance(front_url, str) and "/front/" in front_url:
            card["back_image_url"] = front_url.replace("/front/", "/back/")
            updated += 1
    return updated


def rebuild_cards_table(cards_json_path: Path, db_path: Path) -> int:
    if not cards_json_path.exists():
        raise FileNotFoundError(f"Missing cards dataset: {cards_json_path}")

    print("[2/4] Rebuilding cards table...")
    with cards_json_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    cards = payload.get("cards", [])
    backfilled_back_images = normalize_back_images(cards)
    if backfilled_back_images:
        print(f"Back-image safety fill: {backfilled_back_images} cards")
        # Keep cards.json consistent with what is inserted into SQLite.
        payload["cards"] = cards
        with cards_json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM cards")

    rows = []
    for card in cards:
        rows.append(
            (
                card.get("oracle_id"),
                card.get("name"),
                card.get("card_type"),
                card.get("mana_cost"),
                card.get("cmc"),
                card.get("color"),
                json.dumps(card.get("color_identity", [])),
                card.get("include_pct"),
                json.dumps(card.get("tags", [])),
                json.dumps(card.get("keywords", [])),
                card.get("image_url"),
                card.get("back_image_url"),
                card.get("set"),
                card.get("collector_number"),
            )
        )

    cursor.executemany(
        """
        INSERT INTO cards (
            oracle_id, name, card_type, mana_cost, cmc, color,
            color_identity, include_pct, tags, keywords, image_url,
            back_image_url, "set", collector_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    print(f"Cards table refreshed with {len(rows)} rows")
    return len(rows)


def safe_get(url: str, **kwargs):
    retry_delay = 1.5
    for _ in range(MAX_HTTP_RETRIES):
        try:
            r = requests.get(url, timeout=20, **kwargs)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else retry_delay
                time.sleep(delay)
                retry_delay = min(retry_delay * 1.8, 45)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.8, 45)
    return None


def ensure_oracle_ids(db_path: Path, cards_json_path: Path, sleep_seconds: float) -> int:
    """Safety backfill for legacy/malformed rows with missing oracle_id."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM cards WHERE oracle_id IS NULL OR oracle_id = ''")
    missing_rows = cursor.fetchall()
    if not missing_rows:
        conn.close()
        return 0

    print(f"[3/4] Backfilling oracle_id for {len(missing_rows)} rows...")

    name_to_oracle = {}
    if cards_json_path.exists():
        with cards_json_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        for card in payload.get("cards", []):
            name = card.get("name")
            oracle_id = card.get("oracle_id")
            if name and oracle_id and name not in name_to_oracle:
                name_to_oracle[name] = oracle_id

    fixed = 0
    still_missing = []
    for card_id, name in missing_rows:
        oracle_id = name_to_oracle.get(name)
        if oracle_id:
            cursor.execute("UPDATE cards SET oracle_id = ? WHERE id = ?", (oracle_id, card_id))
            fixed += 1
        else:
            still_missing.append((card_id, name))

    conn.commit()

    # Fallback to Scryfall exact name lookup if anything remains missing.
    for idx, (card_id, name) in enumerate(still_missing, start=1):
        r = safe_get(
            "https://api.scryfall.com/cards/named",
            params={"exact": name},
            headers={"Accept": "application/json"},
        )
        if r is None:
            continue
        data = r.json()
        oracle_id = data.get("oracle_id")
        if oracle_id:
            cursor.execute("UPDATE cards SET oracle_id = ? WHERE id = ?", (oracle_id, card_id))
            fixed += 1
        if idx % 50 == 0:
            conn.commit()
            print(f"oracle backfill progress: {idx}/{len(still_missing)}")
        time.sleep(sleep_seconds)

    conn.commit()
    conn.close()
    return fixed


def fetch_usd_sek_rate() -> float | None:
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
        if not currency or not rate:
            continue
        if currency == "USD":
            usd_rate = float(rate)
        elif currency == "SEK":
            sek_rate = float(rate)

    if usd_rate and sek_rate:
        return sek_rate / usd_rate
    return None


def fetch_cheapest_printing_prices(oracle_id: str):
    url = "https://api.scryfall.com/cards/search"
    params = {"q": f"oracle_id:{oracle_id}", "order": "released"}
    r = safe_get(url, params=params, headers={"Accept": "application/json"})
    if not r:
        return None

    data = r.json()
    cards_list = data.get("data", [])
    if not cards_list:
        return None

    cheapest = None
    cheapest_price = float("inf")
    for printing in cards_list:
        prices = printing.get("prices") or {}
        usd_price = prices.get("usd")
        if not usd_price:
            continue
        try:
            usd_val = float(usd_price)
        except (ValueError, TypeError):
            continue
        if usd_val < cheapest_price:
            cheapest_price = usd_val
            cheapest = prices

    if not cheapest:
        return None

    return {
        "usd": cheapest.get("usd"),
        "usd_foil": cheapest.get("usd_foil"),
        "usd_etched": cheapest.get("usd_etched"),
        "eur": cheapest.get("eur"),
        "eur_foil": cheapest.get("eur_foil"),
        "eur_etched": cheapest.get("eur_etched"),
        "tix": cheapest.get("tix"),
    }


def rebuild_prices(db_path: Path, sleep_seconds: float) -> tuple[int, int, int]:
    print("[4/4] Rebuilding prices table...")
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM prices")

    cursor.execute("SELECT DISTINCT oracle_id FROM cards WHERE oracle_id IS NOT NULL AND oracle_id != ''")
    oracle_ids = [row[0] for row in cursor.fetchall()]

    updated = 0
    skipped = 0
    for idx, oracle_id in enumerate(oracle_ids, start=1):
        price_data = fetch_cheapest_printing_prices(oracle_id)
        if not price_data:
            skipped += 1
            continue

        cursor.execute(
            """
            INSERT OR REPLACE INTO prices (key, usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oracle_id,
                price_data.get("usd"),
                price_data.get("usd_foil"),
                price_data.get("usd_etched"),
                price_data.get("eur"),
                price_data.get("eur_foil"),
                price_data.get("eur_etched"),
                price_data.get("tix"),
            ),
        )
        updated += 1

        if idx % 100 == 0:
            conn.commit()
            print(f"price progress: {idx}/{len(oracle_ids)}")

        time.sleep(sleep_seconds)

    fx_rate = fetch_usd_sek_rate()
    if fx_rate is not None:
        cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ("usd_sek", str(fx_rate)))

    cursor.execute(
        'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
        ("updated_at", datetime.now(timezone.utc).isoformat()),
    )
    cursor.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', ("card_count", str(len(oracle_ids))))

    conn.commit()
    conn.close()
    return len(oracle_ids), updated, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end cards.db refresh")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip cards.json fetch and reuse existing cards.json")
    parser.add_argument("--skip-tagger", action="store_true", help="Skip tagger tags during card fetch")
    parser.add_argument("--pretty", action="store_true", help="Write pretty cards.json during card fetch")
    parser.add_argument("--oracle-sleep", type=float, default=DEFAULT_FETCH_SLEEP, help="Delay between fallback oracle lookup requests")
    parser.add_argument("--price-sleep", type=float, default=DEFAULT_PRICE_SLEEP, help="Delay between price requests")
    args = parser.parse_args()

    started = time.time()

    if not args.skip_fetch:
        run_cards_fetch(skip_tagger=args.skip_tagger, pretty=args.pretty)
    else:
        print("[1/4] Skipped cards fetch (--skip-fetch)")

    card_rows = rebuild_cards_table(CARDS_JSON, DB_FILE)
    backfilled = ensure_oracle_ids(DB_FILE, CARDS_JSON, args.oracle_sleep)
    total_oracle, updated, skipped = rebuild_prices(DB_FILE, args.price_sleep)

    elapsed = time.time() - started
    print("\nRefresh complete")
    print(f"cards rows: {card_rows}")
    print(f"oracle backfilled: {backfilled}")
    print(f"price targets: {total_oracle}, updated: {updated}, skipped: {skipped}")
    print(f"elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
