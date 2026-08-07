import requests, json

hash_id = "07aa200103b683f08a04498c214b117b"
base = f"https://stats.sir.sportradar.com/{hash_id}/fr/page"

test_pages = [
    f"{base}/sportradar_match_summary/3362538",
    f"{base}/sportradar_h2h/3362538",
    f"{base}/sportradar_match_stats/3362538",
    f"{base}/sportradar_team_stats/3362538",
    f"{base}/sportradar_season_fixtures/3362538",
]

H = {'User-Agent': 'Mozilla/5.0'}

for url in test_pages:
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print("  SUCCESS! Data size:", len(r.text))
            try:
                data = json.loads(r.text)
                print("  Keys:", list(data.keys()) if isinstance(data, dict) else "List")
                print("  Snippet:", json.dumps(data)[:300])
            except Exception:
                print("  Snippet:", r.text[:300])
    except Exception as e:
        print("  Error:", e)
