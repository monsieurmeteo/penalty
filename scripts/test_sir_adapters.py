import requests

client_hash = "07aa200103b683f08a04498c214b117b"
base = f"https://widgets.sir.sportradar.com/{client_hash}"

endpoints = [
    f"{base}/adapter/unibet",
    f"{base}/adapter/default",
    f"{base}/translations/fr",
    f"{base}/translations/fr.json",
    "https://widgets.sir.sportradar.com/translations/fr.json",
    f"https://widgets.sir.sportradar.com/translations/fr",
    f"https://stats.sir.sportradar.com/api/v1/h2h/{client_hash}/3362538",
    f"https://widgets.sir.sportradar.com/07aa200103b683f08a04498c214b117b/widgetloader/v2",
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
