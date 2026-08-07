import requests, json

hash_id = "07aa200103b683f08a04498c214b117b"

endpoints = [
    f"https://stats.sir.sportradar.com/sportradar/fr/v1/match/{hash_id}",
    f"https://stats.sir.sportradar.com/sportradar/fr/v1/h2h/{hash_id}",
    f"https://stats.sir.sportradar.com/sportradar/fr/v1/season/{hash_id}",
    f"https://stats.sir.sportradar.com/sportradar/fr/v1/stats/{hash_id}",
    f"https://stats.sir.sportradar.com/sportradar/fr/v1/widgets/{hash_id}",
]

H = {'User-Agent': 'Mozilla/5.0'}

for ep in endpoints:
    try:
        r = requests.get(ep, headers=H, timeout=5)
        print(f"[{r.status_code}] {ep}")
        print("  Response:", r.text[:300])
    except Exception as e:
        print("  Error:", e)
