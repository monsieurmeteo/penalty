"""
Module de scraping et de consensus prédictif multi-sources (Token 0 — Zéro Clé API)
Intègre Wincomparator IA (+2.5 buts) avec moteur de correspondance floue universelle (Fuzzy Matching).
"""

import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import json
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

ALIASES = {
    "psg": "parissg",
    "paris": "parissg",
    "parissaintgermain": "parissg",
    "stetienne": "saintetienne",
    "asstetienne": "saintetienne",
    "assaintetienne": "saintetienne",
    "inter": "intermilan",
    "internazionale": "intermilan",
    "milan": "acmilan",
    "atletico": "atleticomadrid",
    "atleticodemadrid": "atleticomadrid",
    "athbilbao": "athleticbilbao",
    "bilbao": "athleticbilbao",
    "bayern": "bayernmunich",
    "bayernmunchen": "bayernmunich",
    "dortmund": "borussiadortmund",
    "bvb": "borussiadortmund",
    "mgladbach": "monchengladbach",
    "borussiamgladbach": "monchengladbach",
    "leverkusen": "bayerleverkusen",
    "leipzig": "rbleipzig",
    "wolves": "wolverhampton",
    "wolverhamptonwanderers": "wolverhampton",
    "brightonandhovealbion": "brighton",
    "nottingham": "nottinghamforest",
    "tottenhamhotspur": "tottenham",
    "spurs": "tottenham",
    "sporting": "sportingcp",
    "sportinglisbon": "sportingcp",
    "slbenfica": "benfica",
    "bodoglimt": "bodoglimt",
    "ajaxamsterdam": "ajax",
    "feyenoordrotterdam": "feyenoord",
    "psveindhoven": "psv",
    "kobenhavn": "copenhague",
    "copenhagen": "copenhague",
    "crvenazvezda": "etoilerouge",
    "redstar": "etoilerouge",
    "youngboys": "youngboys",
    "bscyoungboys": "youngboys",
    "manutd": "manchesterunited",
    "manunited": "manchesterunited",
    "mancity": "manchestercity",
}

def clean_team_name(name):
    if not name:
        return ""
    name = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('ASCII').lower()
    name = re.sub(r'\b(fc|afc|cf|sc|ac|as|rc|us|ogc|rb|bsc|sk|fk|bk|ff|sv|vfb|vfl|tsv|1\.|cd|ca|ud|sd|de|la|le|les|and|aj)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name).strip()
    return ALIASES.get(name, name)

def is_team_match(name1, name2):
    n1 = clean_team_name(name1)
    n2 = clean_team_name(name2)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    if n1 in n2 or n2 in n1:
        return True
    return SequenceMatcher(None, n1, n2).ratio() >= 0.70

def fetch_wincomparator_predictions(scanned_unibet_matches=None):
    """
    Scrape Wincomparator avec fuzzy matching pour retrouver 100% des correspondances.
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

    # Filtrage intelligent par correspondances floues des noms Unibet
    links_to_fetch = match_links
    if scanned_unibet_matches:
        unibet_tokens = []
        for m in scanned_unibet_matches:
            cd = clean_team_name(m.get("dom", ""))
            ce = clean_team_name(m.get("ext", ""))
            if cd: unibet_tokens.append(cd)
            if ce: unibet_tokens.append(ce)

        filtered_links = []
        for lk in match_links:
            lk_clean = re.sub(r'[^a-z0-9]', '', lk.lower())
            if any(tok in lk_clean or lk_clean in tok or SequenceMatcher(None, tok, lk_clean).ratio() >= 0.60 for tok in unibet_tokens):
                filtered_links.append(lk)
        links_to_fetch = filtered_links or match_links[:80]

    print(f"🌐 Wincomparator : {len(links_to_fetch)} fiches ciblées avec Fuzzy Matching...")

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
                    if dom_name and ext_name:
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

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        parsed_items = list(executor.map(parse_single_match, links_to_fetch[:80]))
    
    for item in parsed_items:
        if item and item["c_dom"] and item["c_ext"]:
            results.append(item)

    print(f"✅ Wincomparator : {len(results)} pronostics extraits avec succès !")
    return results

def find_wincomp_match(unibet_dom, unibet_ext, wincomp_list):
    """
    Retrouve un match Unibet dans la liste Wincomparator par comparaison floue.
    """
    if not wincomp_list:
        return None
    for wc in wincomp_list:
        if is_team_match(unibet_dom, wc["dom"]) and is_team_match(unibet_ext, wc["ext"]):
            return wc
    return None
