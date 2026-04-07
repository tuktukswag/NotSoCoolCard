import requests, json
headers={'User-Agent':'Mozilla/5.0 (compatible; Cardsite/1.0)','Accept':'application/json,text/plain;q=0.9,*/*;q=0.8'}
for u in ['https://archidekt.com/api/decks/21464334/','https://archidekt.com/api/decks/21464334/small/']:
    r=requests.get(u,headers=headers,timeout=15)
    print('URL',u,'status',r.status_code,'content-type',r.headers.get('Content-Type'))
    data=r.json()
    print('TYPE',type(data))
    print('keys',list(data.keys()))
    if 'cards' in data:
        print('cards len',len(data['cards']))
        print('cards first',json.dumps(data['cards'][0],indent=2)[:1200])
    print('-'*60)
