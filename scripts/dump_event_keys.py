import requests, json
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

url = 'https://www.unibet.fr/paris-football/france'
r = requests.get(url, headers=H)
soup = BeautifulSoup(r.text, "html.parser")
urls = list(set([a['href'] for a in soup.find_all('a', href=True) if '/paris-football/' in a['href'] and 'vs' in a['href']]))

target_url = ("https://www.unibet.fr" + urls[0]) if urls else 'https://www.unibet.fr/paris-football/argentine/d1-argentine/3362538/boca-juniors-vs-estudiantes-lp'

r = requests.get(target_url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

for script in soup.find_all('script', type='application/json'):
    content = script.string or ""
    if 'EventsDetail' in content:
        data = json.loads(content)
        events = data.get('EventsDetail', {}).get('events', [])
        if events:
            event = events[0]
            print("Event keys:", list(event.keys()))
            for k, v in event.items():
                if isinstance(v, (dict, list)):
                    if isinstance(v, dict):
                        print(f"  dict '{k}':", list(v.keys())[:10])
                    else:
                        print(f"  list '{k}': len={len(v)}")
                else:
                    print(f"  primitive '{k}': {v}")
