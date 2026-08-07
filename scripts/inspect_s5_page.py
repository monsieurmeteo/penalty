import requests, json, re
from bs4 import BeautifulSoup

routes = [
    "https://s5.sir.sportradar.com/unibet/fr/match/3362538",
    "https://s5.sir.sportradar.com/unibet/fr/match/3368115",
    "https://s5.sir.sportradar.com/unibet/fr/season/1",
    "https://s5.sir.sportradar.com/unibet/fr/1/season/12345",
]

H = {'User-Agent': 'Mozilla/5.0'}

for url in routes:
    r = requests.get(url, headers=H, timeout=5)
    print(f"[{r.status_code}] {url}")
    soup = BeautifulSoup(r.text, 'html.parser')
    scripts = soup.find_all('script')
    print(f"  Scripts found: {len(scripts)}")
    for idx, s in enumerate(scripts):
        stext = s.string or ''
        if 'window.' in stext or 'initial' in stext.lower() or 'state' in stext.lower() or 'json' in s.get('type',''):
            print(f"  Script #{idx} (len={len(stext)}):", stext[:200])
