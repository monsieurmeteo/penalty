import requests, json, re
from bs4 import BeautifulSoup

br_id = "72037248" # Pau vs Annecy FC
url = f"https://s5.sir.sportradar.com/unibet/fr/match/{br_id}"

H = {'User-Agent': 'Mozilla/5.0'}

print("Fetching Sportradar S5 page for Pau vs Annecy FC (Betradar ID:", br_id, ")")
r = requests.get(url, headers=H, timeout=10)
print("Status code:", r.status_code)

soup = BeautifulSoup(r.text, 'html.parser')
scripts = soup.find_all('script')

for s in scripts:
    stext = s.string or ""
    if "__reactRouterContext" in stext:
        print("FOUND streamController script! Length:", len(stext))
        # save payload to scratch file to inspect
        with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "w", encoding="utf-8") as f:
            f.write(stext)
        print("Saved payload to sr_stream_payload.txt!")
        
        # search for stats terms
        for kw in ['Pau', 'Annecy', 'victoire', 'carton', 'but', 'over', 'btts', 'deux']:
            matches = re.findall(kw, stext, re.IGNORECASE)
            print(f"  Term '{kw}': {len(matches)} occurrences")
