import requests, json

client = "unibet"
routes = [
    f"https://s5.sir.sportradar.com/{client}/fr/1",
    f"https://s5.sir.sportradar.com/{client}/fr/match/1",
    f"https://s5.sir.sportradar.com/{client}/fr/season/1",
    f"https://s5.sir.sportradar.com/{client}/fr/h2h/1",
    f"https://s5.sir.sportradar.com/{client}/fr/stats",
    f"https://s5.sir.sportradar.com/{client}/fr/json/match/1",
    f"https://s5.sir.sportradar.com/{client}/fr/json/h2h/1",
    f"https://s5.sir.sportradar.com/{client}/fr/json/page/match_headtohead/1",
]

H = {'User-Agent': 'Mozilla/5.0'}

for url in routes:
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print("  SUCCESS! Text:", r.text[:200])
        else:
            print("  Response:", r.text[:200])
    except Exception as e:
        print("  Error:", e)
