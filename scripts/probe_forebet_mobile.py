from curl_cffi import requests
from bs4 import BeautifulSoup
import re, json

# Testing different user-agents, impersonations, and mobile endpoints
configs = [
    ("chrome110", "https://www.forebet.com/en/football-tips-and-predictions-for-today"),
    ("safari15_5", "https://www.forebet.com/en/football-tips-and-predictions-for-today"),
    ("edge101", "https://www.forebet.com/en/football-tips-and-predictions-for-today"),
    ("chrome120", "https://m.forebet.com/en/"),
    ("chrome120", "https://www.forebet.com/en/predictions-under-over-25-goals"),
    ("chrome120", "https://www.forebet.com/fr/prédictions-par-ligue"),
]

for imp, url in configs:
    h = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
    }
    try:
        r = requests.get(url, headers=h, impersonate=imp, timeout=8)
        print(f"Imp: {imp} | URL: {url} -> Status: {r.status_code}, Len: {len(r.content)}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            print("  Title:", soup.title.text if soup.title else "No title")
    except Exception as e:
        print(f"Error {url}: {e}")
