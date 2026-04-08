import json
import sqlite3
import os

# Paths
CARDS_JSON = 'cards.json'
PRICES_JSON = 'prices.json'
DB_FILE = 'cards.db'

# Connect to SQLite
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# Create tables
cursor.execute('''
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
    back_image_url TEXT
)
''')

cursor.execute('''
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
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
''')

# Strip unnecessary fields
for card in data['cards']:
    for key in list(card.keys()):
        if key not in keep_fields:
            del card[key]

# Load and insert cards
with open(CARDS_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)
    cards = data['cards']
    for card in cards:
        cursor.execute('''
        INSERT INTO cards (oracle_id, name, card_type, mana_cost, cmc, color, color_identity, include_pct, tags, keywords, image_url, back_image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            card.get('oracle_id'),
            card.get('name'),
            card.get('card_type'),
            card.get('mana_cost'),
            card.get('cmc'),
            card.get('color'),
            json.dumps(card.get('color_identity', [])),
            card.get('include_pct'),
            json.dumps(card.get('tags', [])),
            json.dumps(card.get('keywords', [])),
            card.get('image_url'),
            card.get('back_image_url')
        ))

# Load and insert prices
with open(PRICES_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)
    prices = data['prices']
    for key, price_data in prices.items():
        cursor.execute('''
        INSERT INTO prices (key, usd, usd_foil, usd_etched, eur, eur_foil, eur_etched, tix)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            key,
            price_data.get('usd'),
            price_data.get('usd_foil'),
            price_data.get('usd_etched'),
            price_data.get('eur'),
            price_data.get('eur_foil'),
            price_data.get('eur_etched'),
            price_data.get('tix')
        ))
    
    # Insert meta
    cursor.execute('INSERT INTO meta (key, value) VALUES (?, ?)', ('usd_sek', str(data['fx']['usd_sek'])))
    cursor.execute('INSERT INTO meta (key, value) VALUES (?, ?)', ('card_count', str(data['meta']['card_count'])))

# Commit and close
conn.commit()
conn.close()

print("Converted JSON to SQLite database")