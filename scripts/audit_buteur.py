import requests, json
from bs4 import BeautifulSoup

H = {'User-Agent': 'Mozilla/5.0'}

for league in ['coupes-d-europe', 'france', 'espagne', 'angleterre']:
    url = f'https://www.unibet.fr/paris-football/{league}'
    r = requests.get(url, headers=H)
    soup = BeautifulSoup(r.text, 'html.parser')
    urls = list(set([a['href'] for a in soup.find_all('a', href=True)
                     if '/paris-football/' in a['href'] and 'vs' in a['href']]))
    for href in urls[:3]:
        full_url = 'https://www.unibet.fr' + href if href.startswith('/') else href
        try:
            mr = requests.get(full_url, headers=H, timeout=6)
        except Exception:
            continue
        msoup = BeautifulSoup(mr.text, 'html.parser')
        for script in msoup.find_all('script', type='application/json'):
            content = script.string or ''
            if 'EventsDetail' not in content:
                continue
            data = json.loads(content)
            events = data.get('EventsDetail', {}).get('events', [])
            if not events:
                continue
            event = events[0]
            dom = event.get('opponentA', {}).get('label', '?')
            ext = event.get('opponentB', {}).get('label', '?')

            # Lister TOUS les marchés contenant 'buteur' ou 'marqueur'
            all_buteur_markets = []
            for g in event.get('groupedMarkets', []):
                for m in g.get('markets', []):
                    desc_raw = (m.get('description') or '').strip()
                    desc = desc_raw.lower()
                    if any(kw in desc for kw in ['buteur', 'marqueur']):
                        nb = len([o for o in m.get('outcomes', [])
                                  if float(str(o.get('price') or o.get('currentPrice') or 0).replace(',', '.')) > 1.0])
                        all_buteur_markets.append(f'  - "{desc_raw}" ({nb} outcomes)')

            # Marché capturé par notre algo
            for g in event.get('groupedMarkets', []):
                found = False
                for m in g.get('markets', []):
                    desc_raw = (m.get('description') or '').strip()
                    desc = desc_raw.lower()
                    if any(kw in desc for kw in ['buteur', 'buteurs', 'joueur marqueur', 'marqueur']) and \
                       not any(ex in desc for ex in ['double', 'triple', 'combin', '2+', 'duel', 'ou ', 'et ', 'trio', 'quatuor', 'equipe']):
                        prices = []
                        for o in m.get('outcomes', []):
                            p_name = (o.get('description') or '').strip()
                            p_val = float(str(o.get('price') or o.get('currentPrice') or 0).replace(',', '.'))
                            if p_val > 1.0 and p_name:
                                prices.append((p_name, p_val))
                        if prices:
                            avg = sum(p for n, p in prices) / len(prices)
                            closest = min(prices, key=lambda x: abs(x[1] - avg))
                            print(f'MATCH: {dom} vs {ext}')
                            print(f'  URL: {full_url}')
                            print(f'  Marchés "buteur/marqueur" dispo sur Unibet:')
                            for ml in all_buteur_markets:
                                print(ml)
                            print(f'  MARCHE CAPTURÉ PAR L\'ALGO: "{desc_raw}"')
                            print(f'  BUTEUR RETENU: {closest[0]} @ {closest[1]} (moy={avg:.2f})')
                            print()
                        found = True
                        break
                if found:
                    break
