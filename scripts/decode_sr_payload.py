import requests, re
from bs4 import BeautifulSoup

sr_id = "72037248"
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

# The data is in seroval format with escaped JSON
# Unescape \\\" → " and \\\\ → \\ to normalize
decoded = stream_text.replace('\\\\"', '"').replace('\\\\\\\\', '\\\\')

print("After decode length:", len(decoded))

# Search for real stat keywords
for kw in ['winRate', 'btts', 'bothTeams', 'overUnder', 'goalsScored', 'goalsFor', 'goalsAgainst',
           'goalsScoredAvg', 'goalsConcededAvg', 'form', 'scoringConceding']:
    found = re.findall(rf'.{{0,10}}{kw}.{{0,80}}', decoded, re.IGNORECASE)
    if found:
        print(f"\nKey '{kw}':")
        for f in found[:3]:
            print(f"  {f}")
