import requests, re

url = "https://widgets.sir.sportradar.com/07aa200103b683f08a04498c214b117b/widgetloader"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H)
text = r.text

print("Searching for endpoint templates...")
matches = re.findall(r'/[a-zA-Z0-9_\-/]{3,50}', text)
candidates = set()
for m in matches:
    if any(k in m for k in ['widget', 'stat', 'match', 'team', 'h2h', 'season', 'lmt', 'api', 'page']):
        candidates.add(m)

for c in sorted(list(candidates))[:30]:
    print(" ", c)
