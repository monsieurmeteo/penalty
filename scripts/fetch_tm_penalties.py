import requests, json, re
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# Fetch match logs or penalty history for Dynamo Kiev / Qarabag on Transfermarkt
def check_tm_team(team_slug, team_id):
    url = f"https://www.transfermarkt.fr/{team_slug}/spielplan/verein/{team_id}"
    r = requests.get(url, headers=H, timeout=8)
    print(f"[{r.status_code}] TM {team_slug}:")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        print(f"  Rows found: {len(rows)}")

check_tm_team("dynamo-kiew", "338")
check_tm_team("qarabag-agdam", "10613")
