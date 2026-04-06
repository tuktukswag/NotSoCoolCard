# Cardsite + GitHub prices.json updater

## What this package does
- your site reads `cards.json`
- prices are stored separately in `prices.json`
- GitHub Actions updates `prices.json` every 24 hours
- Render serves both files, with no database and no paid cron job

## Files
- `app.py` - web app
- `update_prices_json.py` - price updater script
- `.github/workflows/update_prices.yml` - daily GitHub Action
- `templates/` and `static/` - UI files
- `requirements.txt`

## Render web service
Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
python app.py
```

## Important files in your repo
- `cards.json`
- `prices.json`

If `prices.json` is missing at first, the site still works. Prices just show as empty until the GitHub Action runs.

You can also create an empty starter file:
```json
{
  "meta": {},
  "prices": {}
}
```

## GitHub Actions
This workflow runs:
- every day at 03:00 UTC
- or manually from the Actions tab using `Run workflow`

## Recommended setup
1. Put `cards.json` in the repo root
2. Add this package's files to the same repo
3. Push to GitHub
4. Deploy to Render
5. In GitHub, go to Actions and run `Update prices.json` once manually
6. Render will pick up the updated `prices.json` automatically after the push

## Optional environment variables
- `CARDSITE_JSON` - custom path for cards.json
- `CARDSITE_PRICES_JSON` - custom path for prices.json
- `SCRYFALL_SLEEP` - request pause, default `0.12`

## Notes
- Prices are fetched from Scryfall per exact printing using `set` + `collector_number`
- This keeps prices separate from your main card data
- No database is required
