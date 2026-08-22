"""
Module de scraping Wincomparator (Token 0 — Zéro Clé API)
Extrait les pronostics Over/Under (+2.5 buts / -2.5 buts) et les pourcentages de probabilité IA.
"""

import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import json
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

def clean_team_name(name):
    if not name:
        return ""
    name = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('ASCII').lower()
    name = re.sub(r'\b(fc|afc|cf|sc|ac|as|rc|us|ogc|rb|bsc|sk|fk|bk|ff|sv|vfb|vfl|tsv|1\.|cd|ca|ud|sd|de|la|le|les)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name.strip()

def fetch_wincomparator_predictions():
    """
    Scrape l'ensemble des pronostics football du jour sur Wincomparator.
    Retourne un dictionnaire {(clean_dom, clean_ext): {"market": "+2.5", "prob": 56.0, "url": "..."}}
    """
    url = "https://www.wincomparator.com/fr-fr/pronostics/football/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        print(f"⚠️ Erreur fetch Wincomparator index : {e}")
        return {}

    # Extraction des liens de pronostics
    match_links = []
    seen_urls = set()
    for a in soup.find_all('a', href=re.compile(r'/fr-fr/pronostics/[a-z0-9\-]+-\d+/')):
        href = a['href']
        if href.startswith('/'):
            href = "https://www.wincomparator.com" + href
        if href not in seen_urls:
            seen_urls.add(href)
            match_links.append(href)

    print(f"🌐 Wincomparator : {len(match_links)} fiches matchs détectées...")

    def parse_single_match(match_url):
        try:
            r_m = requests.get(match_url, headers=HEADERS, timeout=8)
            if r_m.status_code != 200:
                return None
            s_m = BeautifulSoup(r_m.text, 'html.parser')
            
            over_h2 = s_m.find(lambda tag: tag.name == 'h2' and 'under/over' in tag.text.lower())
            
            market = None
            prob = 0.0
            
            if over_h2:
                parent_sec = over_h2.find_parent('div') or over_h2.parent
                plus_minus = parent_sec.find(string=re.compile(r'(\+2\.5|-2\.5|plus de 2\.5|moins de 2\.5)', re.I))
                if plus_minus:
                    market = "+2.5" if "+" in plus_minus or "plus" in plus_minus.lower() else "-2.5"
                
                prob_span = parent_sec.find(string=re.compile(r'Probabilité\s*:\s*([\d\.]+)%'))
                if prob_span:
                    m_p = re.search(r'Probabilité\s*:\s*([\d\.]+)%', prob_span)
                    if m_p:
                        prob = float(m_p.group(1))
            
            if not market or prob == 0.0:
                for span in s_m.find_all(string=re.compile(r'Probabilité\s*:\s*([\d\.]+)%')):
                    m_p = re.search(r'Probabilité\s*:\s*([\d\.]+)%', span)
                    if m_p:
                        val = float(m_p.group(1))
                        parent_block = span.find_parent('div')
                        if parent_block:
                            txt = parent_block.text
                            if "+2.5" in txt or "Plus" in txt:
                                market = "+2.5"
                                prob = val
                                break
                            elif "-2.5" in txt or "Moins" in txt:
                                market = "-2.5"
                                prob = val
                                break

            dom_name = ""
            ext_name = ""
            for s_ld in s_m.find_all('script', type='application/ld+json'):
                try:
                    d_ld = json.loads(s_ld.string)
                    if isinstance(d_ld, dict) and d_ld.get('@type') == 'SportsEvent':
                        dom_name = d_ld.get('homeTeam', {}).get('name', '')
                        ext_name = d_ld.get('awayTeam', {}).get('name', '')
                        break
                except Exception:
                    pass

            if dom_name and ext_name:
                return {
                    "dom": dom_name,
                    "ext": ext_name,
                    "c_dom": clean_team_name(dom_name),
                    "c_ext": clean_team_name(ext_name),
                    "market": market or "+2.5",
                    "prob": prob,
                    "url": match_url
                }
        except Exception:
            return None
        return None

    # Parallélisation du fetch
    results = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
        parsed_items = list(executor.map(parse_single_match, match_links[:150]))
    
    for item in parsed_items:
        if item and item["c_dom"] and item["c_ext"]:
            key = (item["c_dom"], item["c_ext"])
            results[key] = item

    print(f"✅ Wincomparator : {len(results)} pronostics Over/Under extraits avec succès !")
    return results

if __name__ == "__main__":
    preds = fetch_wincomparator_predictions()
    for k, v in list(preds.items())[:10]:
        print(f"{v['dom']} vs {v['ext']} -> {v['market']} (Prob: {v['prob']}%)")
