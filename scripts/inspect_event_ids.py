import requests, json

H = {'User-Agent': 'Mozilla/5.0'}
url = 'https://www.unibet.fr/paris-football/france'
r = requests.get(url, headers=H)
soup = BeautifulSoup(r.text, 'html.parser') if 'BeautifulSoup' in globals() else None

from bs4 import BeautifulSoup
soup = BeautifulSoup(r.text, 'html.parser')
urls = list(set([a['href'] for a in soup.find_all('a', href=True) if '/paris-football/' in a['href'] and 'vs' in a['href']]))

for href in urls[:3]:
    full_url = 'https://www.unibet.fr' + href if href.startswith('/') else href
    mr = requests.get(full_url, headers=H, timeout=6)
    msoup = BeautifulSoup(mr.text, 'html.parser')
    for script in msoup.find_all('script', type='application/json'):
        content = script.string or ''
        if 'EventsDetail' in content:
            data = json.loads(content)
            events = data.get('EventsDetail', {}).get('events', [])
            if events:
                event = events[0]
                print(f"Match: {event.get('description')}")
                for k, v in event.items():
                    if 'id' in k.lower() or 'stat' in k.lower() or 'lmt' in k.lower() or 'ref' in k.lower() or 'path' in k.lower() or 'parent' in k.lower():
                        print(f"  {k} = {v}")
