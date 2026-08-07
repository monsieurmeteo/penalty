import requests, re
from bs4 import BeautifulSoup

H = {'User-Agent': 'Mozilla/5.0'}

# The /over_under and /team_stats pages have their own streamController payloads
# Let's extract real numbers from /over_under which should have % Over 2.5, BTTS

for tab, sr_id in [("over_under", "72037248"), ("team_stats", "72037248"), ("season_statistics", "72037248")]:
    url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}/{tab}"
    r = requests.get(url, headers=H, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    for s in soup.find_all('script'):
        stext = s.string or ""
        if len(stext) > 5000 and "streamController" in stext:
            print(f"\n=== /{tab} — Script length: {len(stext)} ===")
            
            # Look for actual number values
            nums = re.findall(r'"(\d{1,3})"', stext)
            pcts = [n for n in nums if 10 <= int(n) <= 95]
            decimals = re.findall(r'(?<!")(\d\.\d{1,2})(?!")', stext)
            
            print(f"  Percentage-range numbers found: {list(set(pcts))[:20]}")
            print(f"  Decimal numbers found: {list(set(decimals))[:15]}")
            
            # Look for score/result sequences like W, D, L
            wdl = re.findall(r'"([WDL])"', stext)
            print(f"  W/D/L results found: {wdl[:15]}")
            
            # Show snippet around interesting numbers
            for num in ['55', '60', '65', '70', '50']:
                ctx = re.findall(rf'.{{0,30}}"{num}".{{0,30}}', stext)
                if ctx:
                    print(f"  Context for '{num}': {ctx[0]}")
