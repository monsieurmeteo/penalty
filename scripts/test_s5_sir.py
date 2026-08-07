import requests

client_hash = "07aa200103b683f08a04498c214b117b"

endpoints = [
    f"https://s5.sir.sportradar.com/{client_hash}/fr/page/match_headtohead/3362538",
    f"https://s5.sir.sportradar.com/{client_hash}/fr/page/player_stats/3362538",
    f"https://s5.sir.sportradar.com/{client_hash}/fr/page/team_stats/3362538",
    f"https://s5.sir.sportradar.com/unibet/fr/page/match_headtohead/3362538",
    f"https://widgets.sir.sportradar.com/{client_hash}/widgets/lmt",
]

H = {'User-Agent': 'Mozilla/5.0'}

for url in endpoints:
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print("  SUCCESS! Response size:", len(r.text))
            print("  Preview:", r.text[:250])
    except Exception as e:
        print("  Error:", e)
