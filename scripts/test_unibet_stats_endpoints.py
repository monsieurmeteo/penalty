import requests, re

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

event_id = "3362708"  # Le Mans vs Brest or 3362538 (Boca Juniors vs Estudiantes)

test_urls = [
    f"https://www.unibet.fr/zones/event/stats.json?eventId={event_id}",
    f"https://www.unibet.fr/zones/event/stats/{event_id}.json",
    f"https://www.unibet.fr/zones/sport/event/stats?eventId={event_id}",
    f"https://www.unibet.fr/api/event/{event_id}/stats",
    f"https://www.unibet.fr/zones/v1/event/{event_id}/stats",
    f"https://www.unibet.fr/zones/v1/stats/{event_id}",
    f"https://www.unibet.fr/zones/stats/{event_id}.json",
    f"https://www.unibet.fr/zones/lmt/{event_id}.json",
    f"https://www.unibet.fr/zones/profile/stats/{event_id}",
]

for url in test_urls:
    try:
        r = requests.get(url, headers=H, timeout=5)
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print("  Content preview:", r.text[:200])
    except Exception as e:
        print(f"[ERR] {url} -> {e}")
