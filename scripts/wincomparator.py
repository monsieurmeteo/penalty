"""
Module de scraping Wincomparator ciblé ultra-rapide (<2 secondes)
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
}

def clean_team_name(name):
    if not name:
        return ""
    name = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('ASCII').lower()
    name = re.sub(r'\b(fc|afc|cf|sc|ac|as|rc|us|ogc|rb|bsc|sk|fk|bk|ff|sv|vfb|vfl|tsv|1\.|cd|ca|ud|sd|de|la|le|les)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name.strip()

def fetch_wincomparator_predictions(scanned_unibet_matches=None):
    """
    Scrape Wincomparator de manière ciblée sur les matchs Unibet.
    """
    url = "https://www.wincomparator.com/fr-fr/pronostics/football/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        print(f"⚠️ Erreur index Wincomparator : {e}")
        return {}

    match_links = []
    seen_urls = set()
    for a in soup.find_all('a', href=re.compile(r'/fr-fr/pronostics/[a-z0-9\-]+-\d+/')):
        href = a['href']
        if href.startswith('/'):
            href = "https://www.wincomparator.com" + href
        if href not in seen_urls:
            seen_urls.add(href)
            match_links.append(href)

    # Filtrage ciblé sur les matchs Unibet si fournis
    links_to_fetch = match_links
    if scanned_unibet_matches:
        unibet_keys = set()
        for m in scanned_unibet_matches:
            cd = clean_team_name(m.get("dom", ""))
            ce = clean_team_name(m.get("ext", ""))
            if cd and ce:
                unibet_keys.add(cd[:5])
                unibet_keys.add(ce[:5])

        filtered_links = []
        for lk in match_links:
            lk_clean = re.sub(r'[^a-z0-9]', '', lk.lower())
            if any(k in lk_clean for k in unibet_keys):
                filtered_links.append(lk)
        links_to_fetch = filtered_links or match_links[:50]

    print(f"🌐 Wincomparator : {len(links_to_fetch)} fiches ciblées à scraper...")

    def parse_single_match(match_url):
        try:
            r_m = requests.get(match_url, headers=HEADERS, timeout=6)
            if r_m.status_code != 200:
                return None
            s_m = BeautifulSoup(r_m.text, 'html.parser')
            
            dom_name = ""
            ext_name = ""
            for s_ld in s_m.find_all('script', type='application/ld+json'):
                try:
                    d_ld = json.loads(s_ld.string)
                    items = d_ld if isinstance(d_ld, list) else [d_ld]
                    for item in items:
                        if isinstance(item, dict) and item.get('@type') == 'SportsEvent':
                            dom_name = item.get('homeTeam', {}).get('name', '')
                            ext_name = item.get('awayTeam', {}).get('name', '')
                            break
                except Exception:
                    pass

            if not dom_name or not ext_name:
                h2_match = s_m.find(lambda tag: tag.name == 'h2' and 'under/over' in tag.text.lower())
                if h2_match:
                    m_teams = re.search(r'([A-Za-z0-9\s\.\-]+)\s*-\s*([A-Za-z0-9\s\.\-]+)\s*:\s*notre', h2_match.text, re.I)
                    if m_teams:
                        dom_name = m_teams.group(1).strip()
                        ext_name = m_teams.group(2).strip()

            market = "+2.5"
            prob = 0.0
            for span in s_m.find_all(string=re.compile(r'Probabilit[ée]\s*:\s*([\d\.]+)%')):
                m_p = re.search(r'Probabilit[ée]\s*:\s*([\d\.]+)%', span)
                if m_p:
                    parent_txt = span.find_parent('div').text if span.find_parent('div') else ""
                    val = float(m_p.group(1))
                    if "+2.5" in parent_txt or "Plus" in parent_txt:
                        market = "+2.5"
                        prob = val
                        break
                    elif "-2.5" in parent_txt or "Moins" in parent_txt:
                        market = "-2.5"
                        prob = val
                        break

            if dom_name and ext_name:
                return {
                    "dom": dom_name,
                    "ext": ext_name,
                    "c_dom": clean_team_name(dom_name),
                    "c_ext": clean_team_name(ext_name),
                    "market": market,
                    "prob": prob,
                    "url": match_url
                }
        except Exception:
            return None
        return None

    results = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        parsed_items = list(executor.map(parse_single_match, links_to_fetch[:60]))
    
    for item in parsed_items:
        if item and item["c_dom"] and item["c_ext"]:
            key = (item["c_dom"], item["c_ext"])
            results[key] = item

    print(f"✅ Wincomparator : {len(results)} pronostics Over/Under extraits avec succès !")
    return results

if __name__ == "__main__":
    sample_matches = [{"dom": "Lens", "ext": "Auxerre"}, {"dom": "Toulouse", "ext": "Lyon"}, {"dom": "Nice", "ext": "Lorient"}]
    res = fetch_wincomparator_predictions(sample_matches)
    for k, v in res.items():
        print(f"  {v['dom']} vs {v['ext']} -> {v['market']} (Prob: {v['prob']}%) | URL: {v['url']}")
