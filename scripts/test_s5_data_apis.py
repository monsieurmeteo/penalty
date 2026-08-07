import requests, re
from bs4 import BeautifulSoup

# The Sportradar s5 page uses a React Router / Seroval format.
# The REAL data (numbers) is loaded dynamically via API calls from the client JS.
# Let's check what API calls the page makes for team stats.

# Try the direct Sportradar data APIs
sr_id = "72037248"

endpoints = [
    f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}/team_stats",
    f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}/season_statistics",
    f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}/over_under",
    f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}/head_to_head",
    f"https://s5.sir.sportradar.com/unibet/fr/data/match/{sr_id}",
    f"https://s5.sir.sportradar.com/api/unibet/fr/match/{sr_id}",
    f"https://s5.sir.sportradar.com/unibet/fr/api/match/{sr_id}/team_statistics",
]

H = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

for ep in endpoints:
    try:
        r = requests.get(ep, headers=H, timeout=5)
        print(f"[{r.status_code}] {ep}")
        if r.status_code == 200:
            print("  Response:", r.text[:200])
    except Exception as e:
        print(f"  Error: {e}")
