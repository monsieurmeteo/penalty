import requests, re

url = 'https://www.unibet.fr/main.b30e9dd6b8699086.js'
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H)
text = r.text

print("Searching for betradar and lmt urls...")
for match in re.finditer(r'(betradar|lmt|widget|stat)', text, re.IGNORECASE):
    idx = match.start()
    snippet = text[max(0, idx-60):min(len(text), idx+120)]
    if any(k in snippet.lower() for k in ['http', 'url', 'api', 'widget', 'betradar', 'sportradar']):
        print("MATCH:", snippet)
