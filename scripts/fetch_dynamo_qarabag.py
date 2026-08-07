import requests, json, re
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

# Search all Unibet football categories for Dynamo Kiev vs Qarabag
countries = [
    "coupes-d-europe", "international", "ukraine", "azerbaidjan", "france", "angleterre"
]

match_url = None
sr_id = None
event_data = None

for c in countries:
    url = f"https://www.unibet.fr/paris-football/{c}"
    try:
        r = requests.get(url, headers=H, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a['href']
                if "dynamo" in href.lower() or "qarabag" in href.lower() or "kiev" in href.lower():
                    full_url = f"https://www.unibet.fr{href}" if href.startswith("/") else href
                    print("Found URL:", full_url)
                    match_url = full_url
                    break
    except Exception:
        pass
    if match_url: break

if match_url:
    r_match = requests.get(match_url, headers=H, timeout=10)
    soup_m = BeautifulSoup(r_match.text, "html.parser")
    for script in soup_m.find_all("script", type="application/json"):
        content = script.string or ""
        if "EventsDetail" in content:
            data = json.loads(content)
            events = data.get("EventsDetail", {}).get("events", [])
            if events:
                event_data = events[0]
                stats_obj = event_data.get("stats") or {}
                lmt_obj   = event_data.get("lmt") or {}
                sr_id     = stats_obj.get("id") or lmt_obj.get("id")
                print("Match found:", event_data.get("description"))
                print("Betradar ID:", sr_id)

if not sr_id:
    # Let's search by crawling all countries
    print("Searching via main unibet listing...")
    r_main = requests.get("https://www.unibet.fr/paris-football", headers=H, timeout=10)
    soup_m = BeautifulSoup(r_main.text, "html.parser")
    for a in soup_m.find_all("a", href=True):
        href = a['href']
        if ("dynamo" in href.lower() or "kiev" in href.lower()) and "qarabag" in href.lower():
            full_url = f"https://www.unibet.fr{href}" if href.startswith("/") else href
            print("Found URL on main:", full_url)
            mr = requests.get(full_url, headers=H, timeout=8)
            msoup = BeautifulSoup(mr.text, "html.parser")
            for script in msoup.find_all("script", type="application/json"):
                content = script.string or ""
                if "EventsDetail" in content:
                    data = json.loads(content)
                    events = data.get("EventsDetail", {}).get("events", [])
                    if events:
                        event_data = events[0]
                        stats_obj = event_data.get("stats") or {}
                        lmt_obj   = event_data.get("lmt") or {}
                        sr_id     = stats_obj.get("id") or lmt_obj.get("id")
                        print("Match found:", event_data.get("description"))
                        print("Betradar ID:", sr_id)
