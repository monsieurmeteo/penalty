from curl_cffi import requests
from bs4 import BeautifulSoup
import re, json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
}

urls = [
    'https://www.forebet.com/en/football-tips-and-predictions-for-today',
    'https://www.forebet.com/en/football-tips-and-predictions-for-today/over-under-2-5-goals',
    'https://www.forebet.com/scripts/getPredictions.php',
    'https://www.forebet.com/en/predictions-under-over-25-goals'
]

for url in urls:
    try:
        r = requests.get(url, headers=headers, impersonate="chrome124", timeout=10)
        print(f"URL: {url} -> Status: {r.status_code}, Length: {len(r.content)}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            print("Title:", soup.title.text if soup.title else "No title")
            matches = soup.find_all('tr', class_=re.compile(r'tr_short|schema_row|tr_0|tr_1'))
            print(f"Matches found: {len(matches)}")
            for m in matches[:3]:
                print(" -", m.get_text(" ", strip=True)[:100])
    except Exception as e:
        print(f"URL: {url} -> Error: {e}")
