# Cardsite + daily prices on Render

## What this package adds
- your site still reads `cards.json`
- prices are stored separately in Render Postgres
- the website merges prices into each card at runtime
- a cron job updates prices every 24h

## Files
- `app.py` - web app
- `update_prices.py` - daily price updater for a Render Cron Job
- `templates/` and `static/` - UI files
- `requirements.txt`

## 1. Put your `cards.json` in this folder
You can either:
- commit `cards.json` into the repo, or
- set `CARDSITE_JSON` to an absolute path

Most people should just keep `cards.json` in the repo folder for now.

## 2. Create a Render Postgres database
In Render:
- New -> PostgreSQL
- wait for it to be ready
- copy the connection string

Set `DATABASE_URL` as an environment variable on both:
- your web service
- your cron job

## 3. Web service settings
Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
python app.py
```

## 4. Cron job settings
Create a new Render Cron Job with the same repo.

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
python update_prices.py
```

Schedule:
```text
0 3 * * *
```

That means once per day at 03:00 UTC.

## 5. Useful environment variables
- `DATABASE_URL` - required for prices
- `CARDSITE_JSON` - optional custom path to your cards file
- `SCRYFALL_SLEEP` - optional pause between price requests, default `0.12`

## 6. Notes
- Prices are fetched from Scryfall per exact printing using `set` + `collector_number`
- This keeps prices separate from your main JSON
- Your site will still work without prices, but price fields will be empty
