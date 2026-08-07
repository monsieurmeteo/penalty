import requests, json, re
from bs4 import BeautifulSoup

sr_id = "73011612"
url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

stream_text = ""
for s in soup.find_all('script'):
    stext = s.string or ""
    if len(stext) > 10000 and "streamController" in stext:
        stream_text = stext
        break

print(f"Stream text retrieved! Length: {len(stream_text)}")

# Extract all quotes / strings from stream text
strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', stream_text)

# Extract key statistics
print("\n=== STATISTIQUES RÉELLES DYNAMO KIEV vs FC QARABAG ===")

# Search for percentages
pcts = re.findall(r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?([^,"]+)', stream_text)
for p in pcts[:15]:
    print(f"  - {p[1]} : {p[0]}%")

# Search for numeric stats
nums = re.findall(r'(\d+\.\d{1,2})\s*(?:\\\\")?\s*,\s*(?:\\\\")?([^,"]+)', stream_text)
for n in nums[:15]:
    print(f"  - {n[1]} : {n[0]}")

# Dump raw occurrences of team names and form
for kw in ['Dynamo', 'Qarabag', 'vict', 'goal', 'card', 'over', 'btts', 'Forme', 'Position']:
    m_cnt = len(re.findall(kw, stream_text, re.IGNORECASE))
    print(f"Keyword '{kw}': {m_cnt} occurrences")
