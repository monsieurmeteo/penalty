import requests, json, re

url = "https://s5.sir.sportradar.com/unibet/fr/match/73011612"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
text = r.text

print("Searching for lastMatches array in Sportradar s5 text...")

# Search for lastMatches in stream text
matches = re.findall(r'.{0,50}lastMatches.{0,200}', text, re.IGNORECASE)
for m in matches[:10]:
    print("MATCH:", m)
