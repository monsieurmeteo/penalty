import json, requests
from bs4 import BeautifulSoup

# Faisons un scan précis des cotes Over 1.5 et Over 2.5 sur les matchs S3 détectés aujourd'hui
matches = [
    {"url": "https://www.unibet.fr/paris-football/coupes-d-europe/europa-league/3368173/kups-vs-uni-craiova", "name": "KuPS vs Uni.Craiova"},
    {"url": "https://www.unibet.fr/paris-football/coupes-d-europe/europa-league/3365821/jagiellonia-vs-rangers", "name": "Jagiellonia vs Rangers"},
    {"url": "https://www.unibet.fr/paris-football/coupes-d-europe/conference-league/3368200/fc-noah-vs-sion", "name": "FC Noah vs Sion"},
    {"url": "https://www.unibet.fr/paris-football/coupes-d-europe/conference-league/3368202/dynamo-kiev-vs-fc-qarabag", "name": "Dynamo Kiev vs FC Qarabag"},
]

H = {"User-Agent": "Mozilla/5.0"}

for m in matches:
    try:
        r = requests.get(m["url"], headers=H, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for js in soup.find_all("script", type="application/json"):
            content = js.string or ""
            if "EventsDetail" in content:
                data = json.loads(content)
                event = data["EventsDetail"]["events"][0]
                o15 = o25 = btts = None
                for g in event.get("groupedMarkets", []):
                    for mk in g.get("markets", []):
                        desc = (mk.get("description") or "").lower()
                        if "plus / moins 1.5" in desc and o15 is None:
                            for o in mk.get("outcomes", []):
                                if "plus" in (o.get("description") or "").lower():
                                    o15 = o.get("price")
                        elif "plus / moins 2.5" in desc and o25 is None:
                            for o in mk.get("outcomes", []):
                                if "plus" in (o.get("description") or "").lower():
                                    o25 = o.get("price")
                        elif "marqueront-elles" in desc and btts is None:
                            for o in mk.get("outcomes", []):
                                if (o.get("description") or "").lower() == "oui":
                                    btts = o.get("price")
                print(f"Match: {m['name']} | Over 1.5: {o15} | Over 2.5: {o25} | BTTS: {btts}")
    except Exception as e:
        print(f"Erreur {m['name']}: {e}")
