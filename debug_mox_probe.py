import requests

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://moxfield.com/',
    'Connection': 'keep-alive',
}

urls = [
    'https://api.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ',
    'https://api.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ/export',
    'https://api2.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ',
    'https://api2.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ/export',
    'https://moxfield.com/decks/p8hyvAd7JUWmljhQLgA1WQ',
]

for u in urls:
    try:
        r = requests.get(u, headers=headers, timeout=15)
        print(u, r.status_code, r.headers.get('Content-Type'))
        print(r.text[:600])
    except Exception as e:
        print(u, 'ERROR', e)
