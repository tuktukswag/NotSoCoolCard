# Cardsite quick start

## 1. Put your JSON file in this folder
Rename your generated JSON file to `cards.json`

or set a custom path with:

```powershell
$env:CARDSITE_JSON="C:\full\path\to\your\cards.json"
py app.py
```

## 2. Install Flask

```powershell
py -m pip install -r requirements.txt
```

## 3. Start the site

```powershell
py app.py
```

Open `http://127.0.0.1:5000`

## New commander filter
You can now:
- tick W/U/B/R/G for your commander
- enable `Limit cards to this commander identity`

Example:
- tick R and W
- enable the checkbox

Then only cards legal in RW color identity will be shown.

## Notes
- This first version reads directly from your JSON file.
- It uses each card's `color_identity` field for commander legality filtering.
