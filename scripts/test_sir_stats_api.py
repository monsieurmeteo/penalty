import requests, json

client_hash = "07aa200103b683f08a04498c214b117b"

endpoints = [
    f"https://stats.sir.sportradar.com/api/v1/h2h/{client_hash}",
    f"https://stats.sir.sportradar.com/api/v1/h2h",
    f"https://stats.sir.sportradar.com/api/v1/{client_hash}/h2h",
    f"https://stats.sir.sportradar.com/api/v1/{client_hash}/season",
    f"https://stats.sir.sportradar.com/api/v1/{client_hash}/match/3362538",
    f"https://stats.sir.sportradar.com/api/v1/{client_hash}/fr/h2h",
]

H = {'User-Agent': 'Mozilla/5.0'}

for ep in endpoints:
    try:
        r = requests.get(ep, headers=H, timeout=5)
        print(f"[{r.status_code}] {ep}")
        print("  Response:", r.text[:250])
    except Exception as e:
        print("  Error:", e)
