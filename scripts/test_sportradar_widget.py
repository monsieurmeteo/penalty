import requests, json

client_hash = "07aa200103b683f08a04498c214b117b"

# Match IDs on Unibet (e.g. 3362538 for Boca vs Estudiantes or 3368115 for Rodez vs Laval)
# Sportradar widgets use sportradar match IDs or mapping endpoints.
# Let's test sportradar endpoints for unibet!

test_urls = [
    f"https://widgets.sir.sportradar.com/{client_hash}/translations/fr.json",
    f"https://stats.betradar.com/ls/api/en/tour/1/2026/h2h/3362538",
    f"https://widgets.sir.sportradar.com/translations/fr.json",
]

H = {'User-Agent': 'Mozilla/5.0'}

for url in test_urls:
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print(" Preview:", r.text[:300])
    except Exception as e:
        print(" ERR:", e)
