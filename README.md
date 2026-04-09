Replace these files in your repo:
- app.py
- templates/index.html
- static/app.js
- static/styles.css

Changes:
- removes top page info text
- removes duplicate price line under each card
- removes duplicate mana value text under each card
- keeps only the corner price and MV pills
- improves Moxfield import with more fallbacks

Database update workflow:
- Run one command to refresh cards and prices in `cards.db`:
	- `python update_all_data.py`
- If `cards.json` is already up to date and you only want DB + prices refresh:
	- `python update_all_data.py --skip-fetch`
- Optional faster fetch without tagger:
	- `python update_all_data.py --skip-tagger`

What the script does:
- Fetches the full card dataset (`cards.json`) via `scryfall_to_json_database_full_dataset.py`.
- Rebuilds the `cards` table in SQLite.
- Backfills any missing `oracle_id` rows (safety for legacy data).
- Rebuilds the `prices` table using cheapest printing by `oracle_id`.
- Updates meta values (`usd_sek`, `updated_at`, `card_count`).
