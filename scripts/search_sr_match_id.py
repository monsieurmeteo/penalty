import requests, json

url = 'https://www.unibet.fr/paris-football/france/ligue-2-bkt/3368115/rodez-vs-laval'
H = {'User-Agent': 'Mozilla/5.0'}

html = requests.get(url, headers=H).text

# Search for any sportradar ID or betradar match ID format
import re
print("Searching for sr: or match IDs in HTML...")
for m in re.finditer(r'(sportradar|betradar|sr:match|lmt)[^\n"\'\`]{0,100}', html, re.IGNORECASE):
    print("MATCH:", m.group(0))
