import json

with open('cards.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

updated = 0
for card in data['cards']:
    if 'Transform' in card.get('keywords', []) and 'image_url' in card and 'back_image_url' not in card:
        card['back_image_url'] = card['image_url'].replace('/front/', '/back/')
        updated += 1

with open('cards.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f'Updated {updated} transform cards')