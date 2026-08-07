import requests, json, re
from bs4 import BeautifulSoup

H = {'User-Agent': 'Mozilla/5.0'}
url = 'https://www.unibet.fr/paris-football/france'
r = requests.get(url, headers=H)
soup = BeautifulSoup(r.text, 'html.parser')
urls = list(set([a['href'] for a in soup.find_all('a', href=True) if '/paris-football/' in a['href'] and 'vs' in a['href']]))

found_penalties = []

for href in urls[:10]:
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
                match_name = event.get('description')
                for g in event.get('groupedMarkets', []):
                    for m in g.get('markets', []):
                        m_desc = (m.get('description') or '').lower()
                        if any(kw in m_desc for kw in ['penalty', 'pénalt', 'tir au but']):
                            outcomes = [f"{o.get('description')} (@{o.get('price') or o.get('currentPrice')})" for o in m.get('outcomes', [])]
                            found_penalties.append((match_name, m.get('description'), outcomes))

print(f"=== RECHERCHE PENALTY SOURCE UNIBET ACTUELLE ===")
print(f"Nombre de matchs scannés : {len(urls[:10])}")
print(f"Marchés penalty trouvés : {len(found_penalties)}")
for m_name, m_desc, outs in found_penalties:
    print(f"  Match : {m_name}")
    print(f"    Marché : {m_desc} -> {outs}")
