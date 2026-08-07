import requests, json, re
from bs4 import BeautifulSoup

url = "https://www.unibet.fr/paris-football/coupes-d-europe/europa-conference/3368591/dynamo-kiev-vs-fc-qarabag"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

penalty_markets = []

for script in soup.find_all('script', type='application/json'):
    content = script.string or ""
    if "EventsDetail" in content:
        data = json.loads(content)
        events = data.get("EventsDetail", {}).get("events", [])
        if events:
            ev = events[0]
            for g in ev.get("groupedMarkets", []):
                for m in g.get("markets", []):
                    m_desc = (m.get("description") or "").lower()
                    if "pénalt" in m_desc or "penalty" in m_desc or "penalty" in m_desc:
                        outcomes = []
                        for o in m.get("outcomes", []):
                            o_desc = (o.get("description") or "").strip()
                            o_price = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            outcomes.append(f"{o_desc} (@{o_price})")
                        penalty_markets.append({
                            "market": m.get("description"),
                            "outcomes": outcomes
                        })

print(f"=== MARCHÉS PENALTY UNIBET (DYNAMO KIEV vs QARABAG) ===")
print(f"Marchés trouvés : {len(penalty_markets)}")
for pm in penalty_markets:
    print(f"  - {pm['market']} : {', '.join(pm['outcomes'])}")
