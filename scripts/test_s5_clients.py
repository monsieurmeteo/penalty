import requests, json

clients = ["unibet", "unibetfr", "unibet_fr", "unibetfrance"]
pages = ["match_headtohead", "match_summary", "season_match", "team_stats"]

H = {'User-Agent': 'Mozilla/5.0'}

for c in clients:
    url = f"https://s5.sir.sportradar.com/{c}/fr/page/match_headtohead/1"
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print("  SUCCESS! Text:", r.text[:200])
        else:
            print("  Response:", r.text[:200])
    except Exception as e:
        print("  Error:", e)
