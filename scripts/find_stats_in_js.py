import requests, re
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

url = 'https://www.unibet.fr/paris-football/france/ligue-2-bkt/3368115/rodez-vs-laval'
r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

script_srcs = [a['src'] for a in soup.find_all('script', src=True)]
print(f"Found {len(script_srcs)} JS files:")

for src in script_srcs:
    if not src.startswith('http'):
        if not src.startswith('/'): src = '/' + src
        src = 'https://www.unibet.fr' + src
    try:
        jsr = requests.get(src, headers=H, timeout=10)
        js_text = jsr.text
        print(f"\n--- Searching in {src[:80]}... (len={len(js_text)}) ---")
        for term in ['sportradar', 'betradar', 'statscore', 'sofascore', 'optastats', 'lmt', 'widgets']:
            if term in js_text.lower():
                print(f"  Found provider keyword '{term}'!")
                # extract context
                idx = js_text.lower().find(term)
                print("  Context:", js_text[max(0, idx-100):min(len(js_text), idx+150)])
    except Exception as e:
        print(" Error:", e)
