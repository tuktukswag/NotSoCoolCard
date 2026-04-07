import requests

headers = {
    'User-Agent': 'Mozilla/5.0 (compatible; Cardsite/1.0)',
    'Accept': 'application/json,text/plain;q=0.9,*/*;q=0.8',
}
url = 'https://archidekt.com/api/decks/21464334/'
r = requests.get(url, headers=headers, timeout=15)
data = r.json()
print('status', r.status_code)
print('keys', list(data.keys()))
print('cards len', len(data.get('cards', [])))
item = data['cards'][0]
print('item keys', list(item.keys()))
print('quantity', type(item.get('quantity')), item.get('quantity'))
print('name field exists', 'name' in item)
print('card keys', list(item.get('card', {}).keys()))
print('card name exists', 'name' in item.get('card', {}))
print('card displayName exists', 'displayName' in item.get('card', {}))
print('card api name', item.get('card', {}).get('name'))
print('card display name', item.get('card', {}).get('displayName'))
print('oracleCard keys', list(item.get('card', {}).get('oracleCard', {}).keys()) if isinstance(item.get('card', {}).get('oracleCard', {}), dict) else 'no oracleCard')
print('oracleCard name', item.get('card', {}).get('oracleCard', {}).get('name'))
