import requests, json

hash_id = "07aa200103b683f08a04498c214b117b"

endpoints = [
    f"https://widgets.sir.sportradar.com/{hash_id}/widgetloader/info",
    f"https://widgets.sir.sportradar.com/{hash_id}/translations/fr.json",
    f"https://widgets.sir.sportradar.com/v2/translations/fr.json",
    f"https://widgets.sir.sportradar.com/{hash_id}/widgets/headtohead",
    f"https://widgets.sir.sportradar.com/{hash_id}/widgets/season",
    f"https://widgets.sir.sportradar.com/common/translations/fr.json",
]

H = {'User-Agent': 'Mozilla/5.0'}

for ep in endpoints:
    try:
        r = requests.get(ep, headers=H, timeout=5)
        print(f"[{r.status_code}] {ep}")
        if r.status_code == 200:
            print("  Response:", r.text[:200])
    except Exception as e:
        print("  Error:", e)
