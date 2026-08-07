import requests, json

url = "https://www.unibet.fr/paris-football/coupes-d-europe/europa-conference/3368591/dynamo-kiev-vs-fc-qarabag"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser') if 'BeautifulSoup' in globals() else None
from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, 'html.parser')

for script in soup.find_all('script', type='application/json'):
    content = script.string or ""
    if "EventsDetail" in content:
        data = json.loads(content)
        events = data.get("EventsDetail", {}).get("events", [])
        if events:
            ev = events[0]
            print("Match:", ev.get("description"))
            print("Total Grouped Markets:", len(ev.get("groupedMarkets", [])))
            for g in ev.get("groupedMarkets", []):
                print(f" Group: {g.get('name')}")
                for m in g.get("markets", []):
                    print(f"   - Market: {m.get('description')}")
