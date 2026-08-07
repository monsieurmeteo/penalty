import requests, json, re
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

def fetch_sr_stats(sr_id):
    if not sr_id: return None
    url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}"
    try:
        r = requests.get(url, headers=H, timeout=8)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.text, 'html.parser')
        for s in soup.find_all('script'):
            stext = s.string or ""
            if len(stext) > 10000 and "streamController" in stext:
                btts_m = re.findall(r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Deux', stext, re.IGNORECASE)
                o25_m = re.findall(r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Plus de 2\.5', stext, re.IGNORECASE)
                goals_m = re.findall(r'(\d+\.\d{1,2})\s*(?:\\\\")?\s*,\s*(?:\\\\")?Total de Buts', stext, re.IGNORECASE)
                
                return {
                    "btts_m": btts_m,
                    "o25_m": o25_m,
                    "goals_m": goals_m,
                    "raw_len": len(stext)
                }
    except Exception as e:
        print(f"Error fetching SR stats for {sr_id}:", e)
    return None

url = 'https://www.unibet.fr/paris-football/france'
r = requests.get(url, headers=H)
soup = BeautifulSoup(r.text, 'html.parser')
urls = list(set([a['href'] for a in soup.find_all('a', href=True) if '/paris-football/' in a['href'] and 'vs' in a['href']]))

for href in urls[:5]:
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
                dom = event.get('opponentA', {}).get('label', '?')
                ext = event.get('opponentB', {}).get('label', '?')
                stats_obj = event.get('stats') or {}
                lmt_obj = event.get('lmt') or {}
                sr_id = stats_obj.get('id') or lmt_obj.get('id')
                print(f"\nMatch: {dom} vs {ext} (SR ID: {sr_id})")
                if sr_id:
                    res = fetch_sr_stats(sr_id)
                    print("  Result:", res)
