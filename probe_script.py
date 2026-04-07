import requests
urls=[
    'https://api.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ',
    'https://api.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ/export',
    'https://api2.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ',
    'https://api2.moxfield.com/v2/decks/all/p8hyvAd7JUWmljhQLgA1WQ/export',
    'https://moxfield.com/decks/p8hyvAd7JUWmljhQLgA1WQ'
]
headers={
    'User-Agent':'Mozilla/5.0 (compatible; Cardsite/1.0)',
    'Accept':'application/json,text/plain;q=0.9,*/*;q=0.8'
}
with open('probe_output.txt','w',encoding='utf-8') as f:
    for u in urls:
        try:
            r=requests.get(u,headers=headers,timeout=15)
            f.write(f"{u} {r.status_code} {r.headers.get('Content-Type')}\n")
            f.write(r.text[:400] + '\n')
        except Exception as e:
            f.write(f"{u} ERROR {e}\n")
    f.write('archidekt\n')
    for u in ['https://archidekt.com/api/decks/21464334/','https://archidekt.com/api/decks/21464334/small/','https://archidekt.com/decks/21464334/icp']:
        try:
            r=requests.get(u,headers=headers,timeout=15)
            f.write(f"{u} {r.status_code} {r.headers.get('Content-Type')}\n")
            f.write(r.text[:400] + '\n')
        except Exception as e:
            f.write(f"{u} ERROR {e}\n")
