import requests, json, re
from bs4 import BeautifulSoup

br_id = "72037248" # Pau vs Annecy FC
url = f"https://s5.sir.sportradar.com/unibet/fr/match/{br_id}"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')
scripts = soup.find_all('script')

for s in scripts:
    stext = s.string or ""
    if len(stext) > 10000 and "streamController" in stext:
        print("Saving main stream script! Length:", len(stext))
        with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "w", encoding="utf-8") as f:
            f.write(stext)
