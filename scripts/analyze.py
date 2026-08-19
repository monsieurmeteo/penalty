# ==============================================================================
# ANALYZE.PY V13 — AFFICHAGE OBLIGATOIRE DES 10 DERNIERS SCORES REELS (DOM & EXT)
# ==============================================================================

import sys, os, requests, json, unicodedata, re
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.adamchoi.co.uk"
BASE_WIDGET = "https://api.choistats.com/api/widget"

HEADERS = {
    "Authorization-Client": "ADAMCHOI.CO.UK",
    "Referer": "https://www.adamchoi.co.uk/",
    "User-Agent": "Mozilla/5.0"
}
WIDGET_HEADERS = {
    "X-AdamChoi-Api-Token": "45834886-68b3-11eb-99f4-9e36325824ad",
    "Referer": "https://www.adamchoi.co.uk/",
    "User-Agent": "Mozilla/5.0"
}

# Dictionnaire des équivalences / traductions Unibet FR -> AdamChoi EN
ALIASES = {
    "saint": "st",
    "vienne": "vienna",
    "prague": "praha",
    "varsovie": "warsaw",
    "lisbonne": "lisbon",
    "bucarest": "bucharest",
    "athenes": "athens",
    "etoile rouge": "red star",
    "depor": "deportivo",
    "dep": "deportivo",
    "atl": "atletico",
    "uni": "universidad",
    "indep": "independiente",
    "sp": "sporting",
    # Abréviations FR/EN étendues
    "wolverhampton": "wolves",
    "manchester": "man",
    "united": "utd",
    "munich": "munchen",
    "paris": "psg",
    "sheffield": "sheff",
    "birmingham": "birmingham",
    "deportivo": "dep",
    "universidad": "uni",
    "atletico": "atl",
    # PSG / clubs parisiens
    "germain": "",       # "Saint-Germain" → supprimé → "psg" seul suffit
    # Clubs Espagnols
    "real": "real",
    "bilbao": "bilbao",
    "sociedad": "sociedad",
    "valladolid": "valladolid",
    "betis": "betis",
    # Clubs Allemands
    "borussia": "bvb",
    "dortmund": "bvb",
    "leverkusen": "leverkusen",
    "werder": "werder",
    "frankfurt": "eintracht",
    "hoffenheim": "hoffenheim",
    "monchengladbach": "gladbach",
    "gladbach": "gladbach",
    # Clubs Anglais
    "tottenham": "spurs",
    "hotspur": "spurs",
    "newcastle": "newcastle",
    "brighton": "brighton",
    "brentford": "brentford",
    "westham": "west ham",
    "aston": "aston",
    "crystal": "crystal",
    # Clubs Italiens
    "juventus": "juve",
    "napoli": "napoli",
    "internazionale": "inter",
    "lazio": "lazio",
    "fiorentina": "fiorentina",
    # Clubs Portugais
    "benfica": "benfica",
    "porto": "porto",
    "sporting": "sporting",
    # Normalisation clubs FR spéciaux (Unibet vs AdamChoi)
    "lyonnais": "ol",      # "Olympique Lyonnais" → "olympique ol" ≈ "Lyon" via similarity
    "lyonnaise": "ol",
    "marseillais": "om",
    "marseille": "om",
    "lille": "losc",
    "rennes": "rennes",
    "lens": "lens",
    "nantes": "nantes",
    "nice": "nice",
    "toulouse": "toulouse",
    # Clubs Néerlandais / Belges
    "ajax": "ajax",
    "feyenoord": "feyenoord",
    "psv": "psv",
    "anderlecht": "anderlecht",
    # Clubs Turcs
    "galatasaray": "galatasaray",
    "fenerbahce": "fenerbahce",
    "besiktas": "besiktas",
    "trabzonspor": "trabzonspor",
}

def clean_str(s):
    if not s: return ""
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')
    s = s.lower().replace("-", " ").replace(".", " ").replace("_", " ").replace("/", " ")
    words = s.split()
    cleaned = []
    for w in words:
        if w in ["fc", "bk", "if", "sc", "ac", "fk", "cd", "sk", "cf", "sv", "v", "vs", "contre", "pec", "ca", "csd", "acs", "msk", "kv"]:
            continue
        cleaned.append(ALIASES.get(w, w))
    return " ".join(cleaned)

def similarity(a, b):
    a_c = clean_str(a)
    b_c = clean_str(b)
    if not a_c or not b_c:
        return 0.0
    if a_c == b_c:
        return 1.0
    if a_c in b_c or b_c in a_c:
        return 0.95
    tokens_a = set(a_c.split())
    tokens_b = set(b_c.split())
    if tokens_a and tokens_b and (tokens_a.issubset(tokens_b) or tokens_b.issubset(tokens_a)):
        return 0.90
    return SequenceMatcher(None, a_c, b_c).ratio()

def fetch(url, headers=HEADERS):
    try:
        r = requests.get(url, headers=headers, timeout=8)
        res = r.json() if r.status_code == 200 else {}
        return res if isinstance(res, (dict, list)) else {}
    except Exception:
        return {}

# Mapping pays Unibet FR → pays AdamChoi EN pour le filtrage par pays
COUNTRY_MAP_FR_EN = {
    "angleterre": "England", "france": "France", "espagne": "Spain",
    "allemagne": "Germany", "italie": "Italy", "portugal": "Portugal",
    "belgique": "Belgium", "pays bas": "Netherlands", "hollande": "Netherlands",
    "ecosse": "Scotland", "turquie": "Turkey", "grece": "Greece",
    "russie": "Russia", "ukraine": "Ukraine", "pologne": "Poland",
    "suede": "Sweden", "norvege": "Norway", "danemark": "Denmark",
    "finlande": "Finland", "suisse": "Switzerland", "autriche": "Austria",
    "republique tcheque": "Czech Republic", "slovaquie": "Slovakia",
    "roumanie": "Romania", "bulgarie": "Bulgaria", "serbie": "Serbia",
    "croatie": "Croatia", "slovenie": "Slovenia", "hongrie": "Hungary",
    "irlande": "Ireland", "irlande du nord": "Northern Ireland",
    "pays de galles": "Wales", "mexique": "Mexico", "bresil": "Brazil",
    "argentine": "Argentina", "chili": "Chile", "colombie": "Colombia",
    "etats unis": "USA", "japon": "Japan", "coree du sud": "South Korea",
    "chine": "China", "australie": "Australia", "israel": "Israel",
    "kazakhstan": "Kazakhstan", "azerbaidjan": "Azerbaijan",
    "albanie": "Albania", "macedoine": "North Macedonia",
    "lettonie": "Latvia", "lituanie": "Lithuania", "estonie": "Estonia",
    "islande": "Iceland", "armenie": "Armenia", "georgie": "Georgia",
    "chypre": "Cyprus", "malte": "Malta", "luxembourg": "Luxembourg",
    "bosnie": "Bosnia", "montenero": "Montenegro",
    # Amérique du Sud
    "equateur": "Ecuador", "uruguay": "Uruguay", "perou": "Peru",
    "venezuela": "Venezuela", "bolivie": "Bolivia", "paraguay": "Paraguay",
    # Afrique
    "afrique du sud": "South Africa", "maroc": "Morocco", "egypte": "Egypt",
    "tunisie": "Tunisia", "algerie": "Algeria", "nigeria": "Nigeria",
    "senegal": "Senegal", "ghana": "Ghana",
    # Asie / reste
    "arabie saoudite": "Saudi Arabia", "emirats": "UAE", "inde": "India",
    "iran": "Iran", "irak": "Iraq",
}

def _extract_country_en(unibet_league: str) -> str:
    """Extrait et traduit le pays depuis le champ league Unibet (ex: 'Angleterre • Championship' -> 'England')"""
    if not unibet_league:
        return ""
    pays_fr = unibet_league.split("•")[0].strip().lower()
    pays_fr = unicodedata.normalize('NFKD', pays_fr).encode('ASCII', 'ignore').decode('ASCII')
    return COUNTRY_MAP_FR_EN.get(pays_fr, "")

def find_fixture_fuzzy(home_query, away_query, fixtures_data=None, match_dt=None, unibet_league=None):
    if not fixtures_data or not isinstance(fixtures_data, dict):
        fixtures_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
    
    target_country = _extract_country_en(unibet_league) if unibet_league else ""
    best_match = None
    best_score = 0.0
    match_ts = match_dt.timestamp() if match_dt else None

    def _search(fixtures_data, country_filter):
        nonlocal best_match, best_score
        for d in fixtures_data.get("dates", []):
            for lg in d.get("leagues", []):
                # Filtrage par pays si disponible
                if country_filter:
                    ac_country = (lg.get("country") or "").strip()
                    if ac_country and ac_country.lower() != country_filter.lower():
                        continue

                for fx in lg.get("fixtures", []):
                    h_name = fx.get("hometeam", "")
                    a_name = fx.get("awayteam", "")

                    if match_ts:
                        fx_ts_ms = fx.get("datetimestamp")
                        if fx_ts_ms:
                            try:
                                fx_ts = float(fx_ts_ms) / 1000.0
                                if abs(match_ts - fx_ts) / 3600.0 > 36.0:
                                    continue
                            except Exception:
                                pass

                    score_h = similarity(home_query, h_name)
                    score_a = similarity(away_query, a_name)
                    combined = (score_h + score_a) / 2.0

                    if combined > best_score:
                        best_score = combined
                        fx_id = fx.get("externalId") or fx.get("externalid") or fx.get("id")
                        best_match = (fx_id, h_name, a_name, lg.get("league"))

    # 1er passage : recherche dans le bon pays uniquement
    if target_country:
        _search(fixtures_data, target_country)

    # Fallback : si pas trouvé dans le pays → recherche globale toutes ligues
    if not best_match or best_score < 0.40:
        best_match = None
        best_score = 0.0
        _search(fixtures_data, "")

    if best_match and best_score >= 0.40:
        return best_match
    
    return "19635927", home_query, away_query, "SA1"

ALIAS_MAP_SOFASCORE = {
    'Paris SG': 'Paris Saint-Germain',
    'AmaZulu': 'AmaZulu FC',
    'Durban City': 'Durban City FC',
    'Torque': 'Montevideo City Torque',
    'Coquimbo U.': 'Coquimbo Unido',
    'Orlando Pir.': 'Orlando Pirates',
    'Hap.Tel Aviv': 'Hapoel Tel Aviv',
    'C.A. Tigre': 'Tigres UANL',
    'Paide': 'Paide Linnameeskond',
    'FC Copenhague': 'FC København',
    'Debrecen': 'Debreceni VSC',
    'Sekhukhune': 'Sekhukhune United',
    'Siwelele': 'Siwelele FC',
    'Bragantino SP': 'Red Bull Bragantino',
    'Atletico MG': 'Atlético Mineiro',
    'Cerro Porteno': 'Cerro Porteño',
    'Atl. San Luis': 'Atlético San Luis',
    'FC Leon': 'Club León',
    'Dallas FC': 'FC Dallas',
    'Dep. Toluca': 'Deportivo Toluca',
    'Seattle': 'Seattle Sounders FC',
    'Chivas': 'CD Guadalajara',
    'Queretaro FC': 'Querétaro FC'
}

def fetch_sofascore_sample(query, is_home=True):
    try:
        from curl_cffi import requests as cf_requests
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        q = ALIAS_MAP_SOFASCORE.get(query, query)
        r = cf_requests.get(f"https://api.sofascore.com/api/v1/search/all?q={q}", impersonate="chrome120", headers=headers, timeout=4)
        if r.status_code == 200:
            teams = [x for x in r.json().get("results", []) if x.get("type") == "team"]
            if teams:
                tid = teams[0]["entity"]["id"]
                r2 = cf_requests.get(f"https://api.sofascore.com/api/v1/team/{tid}/events/last/0", impersonate="chrome120", headers=headers, timeout=4)
                if r2.status_code == 200:
                    events = sorted(r2.json().get("events", []), key=lambda x: x.get("startTimestamp", 0), reverse=True)
                    if is_home:
                        m_list = [e for e in events if e.get("homeTeam", {}).get("id") == tid][:10]
                    else:
                        m_list = [e for e in events if e.get("awayTeam", {}).get("id") == tid][:10]
                    
                    res_matches = []
                    for ev in m_list:
                        hs = ev.get("homeScore", {}).get("current", 0)
                        aws = ev.get("awayScore", {}).get("current", 0)
                        res_matches.append({
                            "homeGoals": hs, "homeGoalsFt": hs,
                            "awayGoals": aws, "awayGoalsFt": aws
                        })
                    return res_matches
    except Exception:
        pass
    return []


def analyze_pure_stats_20(home_query, away_query, fixtures_data=None, is_batch=False, match_dt=None, unibet_league=None, d_refs=None, m_unibet=None):
    ext_id, team_a, team_b, league = find_fixture_fuzzy(home_query, away_query, fixtures_data, match_dt=match_dt, unibet_league=unibet_league)

    if not is_batch:
        print(f"🔍 ÉQUIPES DÉTECTÉES : '{team_a}' vs '{team_b}' ({league})\n")

    # Cherche l'arbitre désigné pour ce match dans le dict pré-chargé d_refs
    ref_info = (d_refs or {}).get(str(ext_id), {})
    ref_id = ref_info.get("refereeId")

    with ThreadPoolExecutor(max_workers=5) as ex:
        f_comp = ex.submit(fetch, f"{BASE}/scripts/data/json/scripts/pages/comparison/getComparisonStatsAsJson.php?clflc=abc&hometeam={team_a}&awayteam={team_b}&hometeamleague={league}&awayteamleague={league}&numrecentmatches=20")
        f_avg  = ex.submit(fetch, f"{BASE_WIDGET}/match/{ext_id}/team-averages?clflc=abc&token=45834886-68b3-11eb-99f4-9e36325824ad", WIDGET_HEADERS)
        f_res  = ex.submit(fetch, f"{BASE_WIDGET}/match/{ext_id}/recent-results?clflc=abc&token=45834886-68b3-11eb-99f4-9e36325824ad", WIDGET_HEADERS)
        f_ref  = ex.submit(fetch, f"{BASE}/scripts/data/json/scripts/pages/referees/getRefereeById.php?clflc=abc&refereeId={ref_id}") if ref_id else None

        comp  = f_comp.result()
        w_avg = f_avg.result()
        w_res = f_res.result()
        ref_career = f_ref.result() if f_ref else {}

    if not isinstance(comp, dict): comp = {}
    if not isinstance(w_avg, dict): w_avg = {}
    if not isinstance(w_res, dict): w_res = {}

    recent_h_all = comp.get("recentmatches", {}).get("homeall", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_a_all = comp.get("recentmatches", {}).get("awayall", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_h_dom = comp.get("recentmatches", {}).get("homehome", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_a_ext = comp.get("recentmatches", {}).get("awayaway", []) if isinstance(comp.get("recentmatches"), dict) else []

    if len(recent_h_dom) < 5 and isinstance(w_res, dict):
        recent_h_dom = (w_res.get("recentHomeAllResults") or []) or (w_res.get("recentHomeResults") or []) or recent_h_dom
    if len(recent_a_ext) < 5 and isinstance(w_res, dict):
        recent_a_ext = (w_res.get("recentAwayAllResults") or []) or (w_res.get("recentAwayResults") or []) or recent_a_ext

    h2h20 = comp.get("headtohead", []) if isinstance(comp.get("headtohead"), list) else []

    h_dom_w = w_avg.get("homeTeam", {}).get("home", {}) if isinstance(w_avg.get("homeTeam"), dict) else {}
    a_ext_w = w_avg.get("awayTeam", {}).get("away", {}) if isinstance(w_avg.get("awayTeam"), dict) else {}

    gf_a = h_dom_w.get("avgGoalsFor", 0.0)
    ga_a = h_dom_w.get("avgGoalsAg", 0.0)
    sot_a = h_dom_w.get("shotsOnTargetFor", 0.0)
    sota_a = h_dom_w.get("shotsOnTargetAg", 0.0)

    gf_b = a_ext_w.get("avgGoalsFor", 0.0)
    ga_b = a_ext_w.get("avgGoalsAg", 0.0)
    sot_b = a_ext_w.get("shotsOnTargetFor", 0.0)
    sota_b = a_ext_w.get("shotsOnTargetAg", 0.0)

    if gf_a == 0.0 and recent_h_dom:
        gf_a = sum(int(m.get("homeGoals", m.get("homeGoalsFt", 0))) for m in recent_h_dom) / len(recent_h_dom)
        ga_a = sum(int(m.get("awayGoals", m.get("awayGoalsFt", 0))) for m in recent_h_dom) / len(recent_h_dom)
        sot_a = (gf_a * 2.3) + 1.8
        sota_a = (ga_a * 2.1) + 1.5

    if gf_b == 0.0 and recent_a_ext:
        gf_b = sum(int(m.get("awayGoals", m.get("awayGoalsFt", 0))) for m in recent_a_ext) / len(recent_a_ext)
        ga_b = sum(int(m.get("homeGoals", m.get("homeGoalsFt", 0))) for m in recent_a_ext) / len(recent_a_ext)
        sot_b = (gf_b * 2.3) + 1.8
        sota_b = (ga_b * 2.1) + 1.5

    # Regress stats to league average if sample N < 5 to prevent extreme anomalies
    n_h = len(recent_h_dom) if isinstance(recent_h_dom, list) else 0
    n_a = len(recent_a_ext) if isinstance(recent_a_ext, list) else 0

    if gf_a == 0.0 and recent_h_dom:
        gf_a = sum(int(m.get("homeGoals", m.get("homeGoalsFt", 0))) for m in recent_h_dom) / max(1, len(recent_h_dom))
        ga_a = sum(int(m.get("awayGoals", m.get("awayGoalsFt", 0))) for m in recent_h_dom) / max(1, len(recent_h_dom))
        sot_a = (gf_a * 2.3) + 1.8
        sota_a = (ga_a * 2.1) + 1.5

    if gf_b == 0.0 and recent_a_ext:
        gf_b = sum(int(m.get("awayGoals", m.get("awayGoalsFt", 0))) for m in recent_a_ext) / max(1, len(recent_a_ext))
        ga_b = sum(int(m.get("homeGoals", m.get("homeGoalsFt", 0))) for m in recent_a_ext) / max(1, len(recent_a_ext))
        sot_b = (gf_b * 2.3) + 1.8
        sota_b = (ga_b * 2.1) + 1.5

    # ponytail: régression douce des stats si échantillon < 5 matchs
    if 0 < n_h < 5:
        gf_a = round((gf_a * n_h + 1.35 * (5 - n_h)) / 5.0, 2)
        ga_a = round((ga_a * n_h + 1.25 * (5 - n_h)) / 5.0, 2)
    if 0 < n_a < 5:
        gf_b = round((gf_b * n_a + 1.15 * (5 - n_a)) / 5.0, 2)
        ga_b = round((ga_b * n_a + 1.35 * (5 - n_a)) / 5.0, 2)

    # Fallback Sofascore Token 0 si AdamChoi n'a pas de données pour ces noms d'équipes
    has_real_data = bool(recent_h_dom or recent_a_ext or h_dom_w or a_ext_w)
    if not has_real_data:
        recent_h_dom = fetch_sofascore_sample(home_query, True)
        recent_a_ext = fetch_sofascore_sample(away_query, False)
        has_real_data = bool(recent_h_dom or recent_a_ext)

    if not has_real_data:
        if is_batch:
            return {
                "score": 0, "classe": "❓ Non analysé", "calibrated_prob": 0,
                "pts_ipo": 0, "ipo_comb": 0, "pts_buts": 0, "avg_buts": 0,
                "pts_freq": 0, "o25_avg_rate": 0, "pts_sot": 0, "sot_comb": 0,
                "pts_ha": 0, "avg_freq_ha": 0, "pts_league": 0,
                "xg_total": 0, "sot_total": 0,
                "verdict": "Équipe non trouvée — données insuffisantes.",
                "red_flags": ["Aucune donnée disponible"],
                "recent_h_dom": [], "recent_a_ext": []
            }
        print(f"❓ {home_query} vs {away_query} — Équipe non trouvée, score non calculé.")
        return

    if gf_a == 0.0: gf_a = 1.4; ga_a = 1.2; sot_a = 4.5; sota_a = 3.2
    if gf_b == 0.0: gf_b = 1.2; ga_b = 1.4; sot_b = 4.1; sota_b = 4.0

    xg_a = (sot_a * 0.28) + (gf_a * 0.5)
    xga_a = (sota_a * 0.28) + (ga_a * 0.5)
    xg_b = (sot_b * 0.28) + (gf_b * 0.5)
    xga_b = (sota_b * 0.28) + (ga_b * 0.5)

    def count_o25(matches_list):
        cnt = 0
        if isinstance(matches_list, list):
            for m in matches_list:
                if isinstance(m, dict):
                    gh = m.get("homeGoals", m.get("homeGoalsFt", 0))
                    ga = m.get("awayGoals", m.get("awayGoalsFt", 0))
                    try:
                        if (int(gh) + int(ga)) >= 3: cnt += 1
                    except Exception: pass
        return cnt

    def count_o15(matches_list):
        cnt = 0
        if isinstance(matches_list, list):
            for m in matches_list:
                if isinstance(m, dict):
                    gh = m.get("homeGoals", m.get("homeGoalsFt", 0))
                    ga = m.get("awayGoals", m.get("awayGoalsFt", 0))
                    try:
                        if (int(gh) + int(ga)) >= 2: cnt += 1
                    except Exception: pass
        return cnt

    def count_btts(matches_list):
        cnt = 0
        if isinstance(matches_list, list):
            for m in matches_list:
                if isinstance(m, dict):
                    gh = m.get("homeGoals", m.get("homeGoalsFt", 0))
                    ga = m.get("awayGoals", m.get("awayGoalsFt", 0))
                    try:
                        if int(gh) >= 1 and int(ga) >= 1: cnt += 1
                    except Exception: pass
        return cnt

    o25_h_cnt = count_o25(recent_h_all[:20])
    o25_a_cnt = count_o25(recent_a_all[:20])
    o25_avg_rate = (((o25_h_cnt / max(1, len(recent_h_all[:20]))) + (o25_a_cnt / max(1, len(recent_a_all[:20])))) / 2.0) * 100

    # ── Calcul fréquence Over 1.5 sur 10 matchs Dom/Ext ──
    o15_h_cnt = count_o15(recent_h_dom[:10])
    o15_a_cnt = count_o15(recent_a_ext[:10])
    freq_o15_dom = (o15_h_cnt / max(1, len(recent_h_dom[:10]))) * 100
    freq_o15_ext = (o15_a_cnt / max(1, len(recent_a_ext[:10]))) * 100
    freq_o15 = round((freq_o15_dom + freq_o15_ext) / 2.0, 1)

    # ── Calcul fréquence BTTS sur 10 matchs Dom/Ext ──
    btts_h_cnt = count_btts(recent_h_dom[:10])
    btts_a_cnt = count_btts(recent_a_ext[:10])
    freq_btts_dom = (btts_h_cnt / max(1, len(recent_h_dom[:10]))) * 100
    freq_btts_ext = (btts_a_cnt / max(1, len(recent_a_ext[:10]))) * 100
    freq_btts = round((freq_btts_dom + freq_btts_ext) / 2.0, 1)

    xg_total = xg_a + ga_b*0.5 + xg_b + ga_a*0.5
    sot_total = sot_a + sot_b

    ds_a = (sot_a >= 5.5 and sota_b >= 4.5) or (gf_a >= 1.7 and ga_b >= 1.4) or (xg_a >= 1.8 and ga_b >= 1.4)
    ds_b = (sot_b >= 5.0 and sota_a >= 4.5) or (gf_b >= 1.6 and ga_a >= 1.4) or (xg_b >= 1.6 and ga_a >= 1.4)

    convergences = []
    if gf_a >= 1.8 and ga_b >= 1.4: convergences.append("Attaque domicile forte × défense extérieure fragile")
    if gf_b >= 1.6 and ga_a >= 1.4: convergences.append("Attaque extérieure productive × défense domicile permissive")
    if xg_a >= 1.7 and xg_b >= 1.5: convergences.append("xG des deux équipes favorables à la création d'occasions")
    if sot_a >= 5.5 and sot_b >= 5.0: convergences.append("Volume de tirs cadrés élevé des deux côtés")
    if o25_avg_rate >= 60.0: convergences.append(f"Forte fréquence historique de matchs à 3+ buts sur 20 matchs ({o25_avg_rate:.0f}%)")
    h2h_o25 = count_o25(h2h20[:10])
    if h2h20 and (h2h_o25 / max(1, len(h2h20[:10]))) >= 0.70:
        convergences.append(f"Historique H2H à {int(h2h_o25/len(h2h20[:10])*100)}%+ d'Over 2.5")

    red_flags = []
    if gf_a < 1.0: red_flags.append(f"Attaque A faible ({gf_a:.1f} goal/m)")
    if gf_b < 1.0: red_flags.append(f"Attaque B faible ({gf_b:.1f} goal/m)")
    if sot_total < 6.5: red_flags.append(f"Tirs cadrés faibles ({sot_total:.1f}/m)")
    if n_h < 3: red_flags.append(f"Échantillon DOM faible ({n_h} m)")
    if n_a < 3: red_flags.append(f"Échantillon EXT faible ({n_a} m)")

    # ══════════════════════════════════════════════════════════════
    # 🟥 MODULE 3 — OVER 2,5 BUTS V3 (/100) — Dual Over Analyzer Spec
    # ══════════════════════════════════════════════════════════════
    ipo_dom = (sot_a * 0.28) + (gf_a * 0.50)
    ipo_ext = (sot_b * 0.28) + (gf_b * 0.50)
    ipo_comb = ipo_dom + ipo_ext

    # Bloc 1 — Potentiel offensif IPO (25 pts max)
    if ipo_comb >= 4.00: o25_b1 = 25
    elif ipo_comb >= 3.70: o25_b1 = 23
    elif ipo_comb >= 3.40: o25_b1 = 21
    elif ipo_comb >= 3.10: o25_b1 = 18
    elif ipo_comb >= 2.80: o25_b1 = 15
    elif ipo_comb >= 2.50: o25_b1 = 11
    elif ipo_comb >= 2.20: o25_b1 = 7
    else: o25_b1 = 4
    if gf_a < 0.80 or gf_b < 0.80: o25_b1 = min(18, o25_b1)

    # Bloc 2 — Buts marqués + encaissés (20 pts max)
    tot_goals_avg = gf_a + ga_a + gf_b + ga_b
    if tot_goals_avg >= 3.40: o25_b2 = 20
    elif tot_goals_avg >= 3.10: o25_b2 = 18
    elif tot_goals_avg >= 2.90: o25_b2 = 16
    elif tot_goals_avg >= 2.70: o25_b2 = 13
    elif tot_goals_avg >= 2.50: o25_b2 = 10
    elif tot_goals_avg >= 2.30: o25_b2 = 6
    else: o25_b2 = 4

    # Bloc 3 — Fréquence Over 2.5 (20 pts max)
    o25_h_dom_cnt = count_o25(recent_h_dom[:10])
    o25_a_ext_cnt = count_o25(recent_a_ext[:10])
    o25_h_dom_rate = (o25_h_dom_cnt / max(1, len(recent_h_dom[:10]))) * 100
    o25_a_ext_rate = (o25_a_ext_cnt / max(1, len(recent_a_ext[:10]))) * 100
    comb_o25_pct = (o25_h_dom_rate + o25_a_ext_rate) / 2.0

    if comb_o25_pct >= 75.0: o25_b3_raw = 20
    elif comb_o25_pct >= 70.0: o25_b3_raw = 18
    elif comb_o25_pct >= 65.0: o25_b3_raw = 16
    elif comb_o25_pct >= 60.0: o25_b3_raw = 13
    elif comb_o25_pct >= 55.0: o25_b3_raw = 10
    elif comb_o25_pct >= 50.0: o25_b3_raw = 6
    elif comb_o25_pct >= 45.0: o25_b3_raw = 3
    else: o25_b3_raw = 0

    o25_b3 = o25_b3_raw
    if min(o25_h_dom_rate, o25_a_ext_rate) < 30.0: o25_b3 = min(6, o25_b3)
    elif min(o25_h_dom_rate, o25_a_ext_rate) < 40.0: o25_b3 = min(10, o25_b3)
    elif min(o25_h_dom_rate, o25_a_ext_rate) < 50.0: o25_b3 = min(14, o25_b3)

    # Bloc 4 — Tirs cadrés (15 pts max)
    sot_comb = sot_a + sot_b
    if sot_comb >= 11.0: o25_b4 = 15
    elif sot_comb >= 10.0: o25_b4 = 13
    elif sot_comb >= 9.0: o25_b4 = 11
    elif sot_comb >= 8.0: o25_b4 = 8
    elif sot_comb >= 7.0: o25_b4 = 5
    else: o25_b4 = 3

    # Bloc 5 — Profil Dom/Ext (10 pts max)
    if o25_h_dom_rate >= 70 and o25_a_ext_rate >= 70: o25_b5 = 10
    elif o25_h_dom_rate >= 50 and o25_a_ext_rate >= 50: o25_b5 = 8
    elif o25_h_dom_rate >= 40 or o25_a_ext_rate >= 40: o25_b5 = 6
    else: o25_b5 = 4

    # Bloc 6 — Ligue/Contexte (10 pts max)
    o25_b6 = 8

    rf_pen_o25 = min(20, len(red_flags) * 10)
    total_score = max(0, min(100, o25_b1 + o25_b2 + o25_b3 + o25_b4 + o25_b5 + o25_b6 - rf_pen_o25))

    if total_score >= 90: classe = "🔥🔥🔥 Exceptionnel"
    elif total_score >= 85: classe = "🔥🔥 Très fort"
    elif total_score >= 80: classe = "🔥 Fort"
    elif total_score >= 75: classe = "✅ Bon potentiel"
    elif total_score >= 70: classe = "🟡 Intéressant mais à confirmer"
    elif total_score >= 65: classe = "⚠️ Moyen"
    elif total_score >= 60: classe = "⚠️ Fragile"
    else: classe = "❌ À écarter"

    verdict = f"{classe} ({total_score}/100)"

    # ══════════════════════════════════════════════════════════════
    # 🟦 MODULE 2 — OVER 1.5 BUTS (/100) — Dual Over Analyzer Spec
    # ══════════════════════════════════════════════════════════════
    # Bloc 1 — Buts marqués + encaissés (25 pts max)
    if tot_goals_avg >= 3.20: o15_b1 = 25
    elif tot_goals_avg >= 3.00: o15_b1 = 23
    elif tot_goals_avg >= 2.80: o15_b1 = 21
    elif tot_goals_avg >= 2.60: o15_b1 = 18
    elif tot_goals_avg >= 2.40: o15_b1 = 15
    elif tot_goals_avg >= 2.20: o15_b1 = 11
    elif tot_goals_avg >= 2.00: o15_b1 = 7
    else: o15_b1 = 4

    # Bloc 2 — Fréquence Over 1.5 (25 pts max)
    o15_h_dom_cnt = count_o15(recent_h_dom[:10])
    o15_a_ext_cnt = count_o15(recent_a_ext[:10])
    pct_o15_h = (o15_h_dom_cnt / max(1, len(recent_h_dom[:10]))) * 100.0
    pct_o15_a = (o15_a_ext_cnt / max(1, len(recent_a_ext[:10]))) * 100.0
    comb_o15_pct = (pct_o15_h + pct_o15_a) / 2.0

    if comb_o15_pct >= 90.0: o15_b2_raw = 25
    elif comb_o15_pct >= 85.0: o15_b2_raw = 23
    elif comb_o15_pct >= 80.0: o15_b2_raw = 21
    elif comb_o15_pct >= 75.0: o15_b2_raw = 18
    elif comb_o15_pct >= 70.0: o15_b2_raw = 15
    elif comb_o15_pct >= 65.0: o15_b2_raw = 11
    elif comb_o15_pct >= 60.0: o15_b2_raw = 7
    else: o15_b2_raw = 4

    o15_b2 = o15_b2_raw
    if min(pct_o15_h, pct_o15_a) < 50.0: o15_b2 = min(8, o15_b2)
    elif min(pct_o15_h, pct_o15_a) < 60.0: o15_b2 = min(13, o15_b2)
    elif min(pct_o15_h, pct_o15_a) < 70.0: o15_b2 = min(18, o15_b2)

    # Bloc 3 — Potentiel offensif (15 pts max)
    if ipo_comb >= 4.00: o15_b3 = 15
    elif ipo_comb >= 3.60: o15_b3 = 13
    elif ipo_comb >= 3.20: o15_b3 = 11
    elif ipo_comb >= 2.80: o15_b3 = 8
    elif ipo_comb >= 2.40: o15_b3 = 5
    else: o15_b3 = 3

    # Bloc 4 — Tirs cadrés (15 pts max)
    if sot_comb >= 10.0: o15_b4 = 15
    elif sot_comb >= 9.0: o15_b4 = 13
    elif sot_comb >= 8.0: o15_b4 = 11
    elif sot_comb >= 7.0: o15_b4 = 8
    elif sot_comb >= 6.0: o15_b4 = 5
    else: o15_b4 = 3

    # Bloc 5 — Profil Dom/Ext (10 pts max)
    o15_b5 = 10 if (pct_o15_h >= 80 and pct_o15_a >= 80) else (8 if (pct_o15_h >= 70 or pct_o15_a >= 70) else 6)

    # Bloc 6 — Ligue/Contexte (10 pts max)
    o15_b6 = 9

    rf_o15 = [f for f in red_flags if "Attaque" in f or "Échantillon" in f]
    rf_pen_o15 = min(15, len(rf_o15) * 5)
    score_o15 = max(0, min(100, o15_b1 + o15_b2 + o15_b3 + o15_b4 + o15_b5 + o15_b6 - rf_pen_o15))

    # ══════════════════════════════════════════════════════════════
    # 🟩 MODULE 4 — BTTS OUI (/100) — BTTS Analyzer Spec
    # ══════════════════════════════════════════════════════════════
    btts_h_cnt = count_btts(recent_h_dom[:10])
    btts_a_cnt = count_btts(recent_a_ext[:10])
    pct_btts_h = (btts_h_cnt / max(1, len(recent_h_dom[:10]))) * 100.0
    pct_btts_a = (btts_a_cnt / max(1, len(recent_a_ext[:10]))) * 100.0
    comb_btts_pct = (pct_btts_h + pct_btts_a) / 2.0

    score_cnt_h = sum(1 for m in recent_h_dom[:10] if int(m.get("homeGoals", m.get("homeGoalsFt", 0))) > 0)
    score_cnt_a = sum(1 for m in recent_a_ext[:10] if int(m.get("awayGoals", m.get("awayGoalsFt", 0))) > 0)
    pct_score_h = (score_cnt_h / max(1, len(recent_h_dom[:10]))) * 100.0
    pct_score_a = (score_cnt_a / max(1, len(recent_a_ext[:10]))) * 100.0
    avg_score_pct = (pct_score_h + pct_score_a) / 2.0

    concede_cnt_h = sum(1 for m in recent_h_dom[:10] if int(m.get("awayGoals", m.get("awayGoalsFt", 0))) > 0)
    concede_cnt_a = sum(1 for m in recent_a_ext[:10] if int(m.get("homeGoals", m.get("homeGoalsFt", 0))) > 0)
    pct_concede_h = (concede_cnt_h / max(1, len(recent_h_dom[:10]))) * 100.0
    pct_concede_a = (concede_cnt_a / max(1, len(recent_a_ext[:10]))) * 100.0
    avg_concede_pct = (pct_concede_h + pct_concede_a) / 2.0

    pct_cs_h = 100.0 - pct_concede_h
    pct_cs_a = 100.0 - pct_concede_a

    # Bloc 1 — Fréquence BTTS (25 pts max)
    if comb_btts_pct >= 75.0: btts_b1_raw = 25
    elif comb_btts_pct >= 70.0: btts_b1_raw = 23
    elif comb_btts_pct >= 65.0: btts_b1_raw = 21
    elif comb_btts_pct >= 60.0: btts_b1_raw = 18
    elif comb_btts_pct >= 55.0: btts_b1_raw = 14
    elif comb_btts_pct >= 50.0: btts_b1_raw = 10
    elif comb_btts_pct >= 45.0: btts_b1_raw = 5
    else: btts_b1_raw = 3

    btts_b1 = btts_b1_raw
    if min(pct_btts_h, pct_btts_a) < 30.0: btts_b1 = min(7, btts_b1)
    elif min(pct_btts_h, pct_btts_a) < 40.0: btts_b1 = min(12, btts_b1)
    elif min(pct_btts_h, pct_btts_a) < 50.0: btts_b1 = min(17, btts_b1)

    # Bloc 2 — Capacité à marquer (20 pts max)
    if avg_score_pct >= 90.0: btts_b2_raw = 20
    elif avg_score_pct >= 85.0: btts_b2_raw = 18
    elif avg_score_pct >= 80.0: btts_b2_raw = 16
    elif avg_score_pct >= 75.0: btts_b2_raw = 13
    elif avg_score_pct >= 70.0: btts_b2_raw = 10
    elif avg_score_pct >= 65.0: btts_b2_raw = 7
    else: btts_b2_raw = 4

    btts_b2 = btts_b2_raw
    if gf_a < 0.70 or gf_b < 0.70: btts_b2 = min(8, btts_b2)
    elif gf_a < 0.90 or gf_b < 0.90: btts_b2 = min(13, btts_b2)

    # Bloc 3 — Capacité à encaisser (20 pts max)
    if avg_concede_pct >= 80.0: btts_b3_raw = 20
    elif avg_concede_pct >= 75.0: btts_b3_raw = 18
    elif avg_concede_pct >= 70.0: btts_b3_raw = 16
    elif avg_concede_pct >= 65.0: btts_b3_raw = 13
    elif avg_concede_pct >= 60.0: btts_b3_raw = 10
    elif avg_concede_pct >= 55.0: btts_b3_raw = 7
    else: btts_b3_raw = 4

    btts_b3 = btts_b3_raw
    max_cs = max(pct_cs_h, pct_cs_a)
    if max_cs >= 70.0: btts_b3 = min(5, btts_b3)
    elif max_cs >= 60.0: btts_b3 = min(8, btts_b3)
    elif max_cs >= 50.0: btts_b3 = min(12, btts_b3)

    # Bloc 4 — Tirs cadrés (15 pts max)
    if sot_comb >= 11.0: btts_b4_raw = 15
    elif sot_comb >= 10.0: btts_b4_raw = 13
    elif sot_comb >= 9.0: btts_b4_raw = 11
    elif sot_comb >= 8.0: btts_b4_raw = 8
    elif sot_comb >= 7.0: btts_b4_raw = 5
    else: btts_b4_raw = 3

    btts_b4 = btts_b4_raw
    if min(sot_a, sot_b) < 2.5: btts_b4 = min(7, btts_b4)
    elif min(sot_a, sot_b) < 3.0: btts_b4 = min(10, btts_b4)

    # Bloc 5 & 6 — Profil Dom/Ext (10 pts) & Ligue (10 pts)
    btts_b5 = 10 if (pct_btts_h >= 70 and pct_btts_a >= 70) else (8 if (pct_btts_h >= 55 and pct_btts_a >= 55) else 6)
    btts_b6 = 8

    rf_btts = []
    if gf_a < 0.8: rf_btts.append(f"Attaque DOM trop faible ({gf_a:.1f} goal/m)")
    if gf_b < 0.8: rf_btts.append(f"Attaque EXT trop faible ({gf_b:.1f} goal/m)")

    unibet_o25 = m_unibet.get("over25") if isinstance(m_unibet, dict) else None
    unibet_btts = m_unibet.get("btts_oui") if isinstance(m_unibet, dict) else None
    if (gf_a >= 2.2 and gf_b < 1.0) or (gf_b >= 2.0 and gf_a < 1.0):
        rf_btts.append(f"Risque Clean Sheet / Déséquilibre offensif majeur ({gf_a:.1f} vs {gf_b:.1f})")
    elif unibet_o25 and unibet_btts and unibet_o25 <= 1.42 and unibet_btts >= 2.00:
        rf_btts.append(f"Risque Clean Sheet Bookmaker (Over 2.5 @{unibet_o25:.2f} vs BTTS @{unibet_btts:.2f})")

    rf_pen_btts = min(25, len(rf_btts) * 12)
    score_btts = max(0, min(100, btts_b1 + btts_b2 + btts_b3 + btts_b4 + btts_b5 + btts_b6 - rf_pen_btts))

    # ══════════════════════════════════════════════════════════════
    # BARÈME V2.1 PENALTY /100 — Refonte prioritaire (Total exact 100 pts)
    # ══════════════════════════════════════════════════════════════

    # 1. Arbitre Désigné avec Facteur de Fiabilité (35 pts max si connu)
    ref_name = ref_info.get("refereeName") or ""
    pen_per_match = 0.0
    total_games = 0
    if isinstance(ref_career, dict) and ref_career.get("seasons"):
        if not ref_name:
            ref_name = ref_career.get("name", "")
        # Saisons récentes (Europe 2025/2026, Amériques/MLS/Asie 2026 et 2025)
        accepted_seasons = ["2025/2026", "2026", "2025"]
        total_pens = 0
        for s in ref_career["seasons"]:
            if str(s.get("season", "")) in accepted_seasons:
                total_pens += s.get("totalPenalties", 0) or 0
                total_games += s.get("fixtureCount", 0) or 0
        if total_games > 0:
            pen_per_match = total_pens / total_games
    ref_name = ref_name or "Inconnu"

    ref_is_known = bool(ref_name != "Inconnu")
    if ref_is_known:
        if pen_per_match >= 0.50: p_pen_ref_raw = 35
        elif pen_per_match >= 0.40: p_pen_ref_raw = 30
        elif pen_per_match >= 0.30: p_pen_ref_raw = 24
        elif pen_per_match >= 0.25: p_pen_ref_raw = 18
        elif pen_per_match >= 0.20: p_pen_ref_raw = 12
        elif pen_per_match >= 0.15: p_pen_ref_raw = 6
        elif pen_per_match > 0: p_pen_ref_raw = 2
        else: p_pen_ref_raw = 10 if total_games == 0 else 0

        # Facteur de Fiabilité R_ref basé sur le nombre de matchs arbitrés cette saison (cible 8+ matchs)
        r_ref = min(1.0, total_games / 8.0) if total_games > 0 else 0.50
        p_pen_ref = round(p_pen_ref_raw * r_ref + 10 * (1.0 - r_ref))
        if total_games > 0:
            ref_status = f"👨‍⚖️ Arbitre {ref_name} ({total_games} m, {pen_per_match:.2f} pen/m)"
        else:
            ref_status = f"👨‍⚖️ Arbitre {ref_name} (désigné — début de saison)"
    else:
        p_pen_ref = 0
        ref_status = "Arbitre non désigné — confiance réduite"

    # 2. Tirs Cadrés & Intensité Offensive (25 pts max)
    if sot_comb >= 13.0: p_pen_sot = 25
    elif sot_comb >= 11.0: p_pen_sot = 21
    elif sot_comb >= 9.0: p_pen_sot = 17
    elif sot_comb >= 7.0: p_pen_sot = 12
    elif sot_comb >= 5.0: p_pen_sot = 7
    else: p_pen_sot = 2

    # 3. Fautes, Cartons & Booking Points (20 pts max — poids réduit)
    h2h_booking = []
    for m in h2h20:
        hbp = m.get("homeBookingPts", 0) or m.get("homeBookingPoints", 0)
        abp = m.get("awayBookingPts", 0) or m.get("awayBookingPoints", 0)
        try:
            h2h_booking.append(int(hbp) + int(abp))
        except (ValueError, TypeError):
            pass

    # ── COMPÉTENCE PENO : Sofascore Token 0 (curl_cffi) + Cache JSON 24h ──
    # ponytail: cache = une seule requête par équipe par journée, résultats déterministes
    import os as _os, time as _time, json as _json
    _CACHE_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pen_cache.json")
    _CACHE_TTL  = 86400  # 24h

    def _load_cache():
        try:
            if _os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                    return _json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(cache):
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                _json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    _sf_cache = _load_cache()

    def fetch_sofascore_penalties(t_name):
        """Retourne (total, obtenus, concedes) sur les 10 derniers matchs — avec cache 24h."""
        if not t_name: return None, None, None
        now = _time.time()
        entry = _sf_cache.get(t_name)
        if entry and now - entry.get("ts", 0) < _CACHE_TTL:
            return entry["tot"], entry["obt"], entry["cnc"]
        try:

            from curl_cffi import requests as cf_requests
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            q_name = ALIAS_MAP_SOFASCORE.get(t_name, t_name)
            r = cf_requests.get(f"https://api.sofascore.com/api/v1/search/all?q={q_name}", impersonate="chrome120", headers=headers, timeout=6)
            if r.status_code == 200:
                teams = [x for x in r.json().get("results", []) if x.get("type") == "team"]
                if teams:
                    t_id = teams[0]["entity"]["id"]
                    r_ev = cf_requests.get(f"https://api.sofascore.com/api/v1/team/{t_id}/events/last/0", impersonate="chrome120", headers=headers, timeout=6)
                    if r_ev.status_code == 200:
                        events = sorted(r_ev.json().get("events", []), key=lambda x: x.get("startTimestamp", 0), reverse=True)
                        def _chk_inc(ev):
                            tot = obt = cnc = 0
                            try:
                                ev_id = ev.get("id")
                                if not ev_id: return 0, 0, 0
                                is_home_ev = (ev.get("homeTeam", {}).get("id") == t_id)
                                r_inc = cf_requests.get(f"https://api.sofascore.com/api/v1/event/{ev_id}/incidents", impersonate="chrome120", headers=headers, timeout=6)
                                if r_inc.status_code == 200:
                                    for inc in r_inc.json().get("incidents", []):
                                        is_pen = (inc.get("incidentClass") == "penalty" or
                                                  inc.get("incidentType") in ["penalty", "penalty_missed", "inGamePenalty"] or
                                                  inc.get("isPenalty"))
                                        if is_pen:
                                            tot += 1
                                            is_inc_home = inc.get("isHome")
                                            if is_inc_home is None:
                                                obt += 1
                                            elif is_home_ev == is_inc_home:
                                                obt += 1
                                            else:
                                                cnc += 1
                            except Exception:
                                pass
                            return tot, obt, cnc
                        with ThreadPoolExecutor(max_workers=5) as p_ex:
                            res_list = list(p_ex.map(_chk_inc, events[:10]))
                            tot = sum(r[0] for r in res_list)
                            obt = sum(r[1] for r in res_list)
                            cnc = sum(r[2] for r in res_list)
                            _sf_cache[t_name] = {"ts": now, "tot": tot, "obt": obt, "cnc": cnc}
                            return tot, obt, cnc
        except Exception:
            pass
        return None, None, None

    p_dom_sf_tot, p_dom_sf_obt, p_dom_sf_cnc = fetch_sofascore_penalties(team_a)
    p_ext_sf_tot, p_ext_sf_obt, p_ext_sf_cnc = fetch_sofascore_penalties(team_b)
    _save_cache(_sf_cache)  # persist après les deux fetches


    bp_dom = h_dom_w.get("bookingPointsTotal", 0.0) or (h_dom_w.get("cardsTotal", 0.0) * 10.0)
    bp_ext = a_ext_w.get("bookingPointsTotal", 0.0) or (a_ext_w.get("cardsTotal", 0.0) * 10.0)

    if p_dom_sf_tot is not None:
        p_dom_10m = p_dom_sf_tot
    else:
        p_dom_10m = min(4, max(2, round(gf_a + (sot_a / 3.0)))) if (gf_a >= 1.2 or sot_a >= 4.0) else 1

    if p_ext_sf_tot is not None:
        p_ext_10m = p_ext_sf_tot
    else:
        p_ext_10m = min(4, max(2, round(gf_b + (sot_b / 3.0)))) if (gf_b >= 1.2 or sot_b >= 4.0) else 1

    # Obtenus/Concédés (fallback si Sofascore muet)
    obt_dom = p_dom_sf_obt if p_dom_sf_obt is not None else max(0, p_dom_10m - 1)
    cnc_dom = p_dom_sf_cnc if p_dom_sf_cnc is not None else max(0, p_dom_10m - obt_dom)
    obt_ext = p_ext_sf_obt if p_ext_sf_obt is not None else max(0, p_ext_10m - 1)
    cnc_ext = p_ext_sf_cnc if p_ext_sf_cnc is not None else max(0, p_ext_10m - obt_ext)

    p_tot_10m = p_dom_10m + p_ext_10m
    p_min_10m = min(p_dom_10m, p_ext_10m)

    # ── BARÈME V2c — 50/50 Arbitre + Pénaltys équipes ──────────────────────
    # Pilier 1 : Arbitre /50 (ratio corrigé bayésien, calculé plus bas avec V3)
    # Pilier 2 : Pénaltys équipes /50 (min des 2 équipes, REJET si < 3)

    # Pilier 2 : Pénaltys équipes — calculé maintenant (données disponibles)
    if p_min_10m < 3:
        pts_pen_teams = 0
        peno_status   = "REJET"
        peno_badge    = f"🛑 REJET PENO (<3 sur les 2 équipes : dom {p_dom_10m}, ext {p_ext_10m})"
    elif p_min_10m >= 4 and p_tot_10m >= 9:
        pts_pen_teams = 50; peno_status = "DOUBLE_SIGNAL"
        peno_badge = f"🔥 DS FORT ({p_dom_10m} dom / {p_ext_10m} ext — total {p_tot_10m})"
    elif p_min_10m >= 4 and p_tot_10m >= 7:
        pts_pen_teams = 44; peno_status = "DOUBLE_SIGNAL"
        peno_badge = f"🔥 DOUBLE SIGNAL ({p_dom_10m} dom / {p_ext_10m} ext — total {p_tot_10m})"
    elif p_min_10m >= 3 and p_tot_10m >= 8:
        pts_pen_teams = 42; peno_status = "DOUBLE_SIGNAL"
        peno_badge = f"🔥 DOUBLE SIGNAL ({p_dom_10m} dom / {p_ext_10m} ext — total {p_tot_10m})"
    elif p_min_10m >= 3 and p_tot_10m >= 7:
        pts_pen_teams = 38; peno_status = "DOUBLE_SIGNAL"
        peno_badge = f"🟢 VALIDE ({p_dom_10m} dom / {p_ext_10m} ext — total {p_tot_10m})"
    else:  # min >= 3, total == 6
        pts_pen_teams = 36; peno_status = "VALIDE"
        peno_badge = f"🟢 VALIDE ({p_dom_10m} dom / {p_ext_10m} ext — total {p_tot_10m})"

    # Pilier 1 : Arbitre /50 — on utilise pen_per_match (ratio brut AdamChoi)
    # La régularisation bayésienne est appliquée dans le bloc V3 plus bas ;
    # ici on utilise le ratio brut pour le barème V2c (cohérent avec l'affichage)
    if not ref_is_known:
        pts_pen_arb = 0
    elif pen_per_match >= 0.50: pts_pen_arb = 50
    elif pen_per_match >= 0.40: pts_pen_arb = 44
    elif pen_per_match >= 0.35: pts_pen_arb = 38
    elif pen_per_match >= 0.30: pts_pen_arb = 30
    elif pen_per_match >= 0.25: pts_pen_arb = 18
    elif pen_per_match >= 0.20: pts_pen_arb = 8
    else:                       pts_pen_arb = 0

    score_penalty = max(0, min(100, pts_pen_arb + pts_pen_teams))

    # Rétro-compat : conserver les anciens noms utilisés dans auto_premium_unibet
    p_pen_ref   = pts_pen_arb
    pts_pen_ref = pts_pen_arb
    pts_pen_sot = pts_pen_teams   # réutilisé pour l'email (affiché comme Pen/50)
    pts_pen_cards = 0
    pts_pen_goals = 0
    total_goals_brut = tot_goals_avg  # toujours calculé pour Over 2.5
    avg_booking = 40.0  # conservé pour Over 2.5

    # Recalcul avg_booking réel (utilisé par Over 2.5)
    bp_dom = h_dom_w.get("bookingPointsTotal", 0.0) or (h_dom_w.get("cardsTotal", 0.0) * 10.0)
    bp_ext = a_ext_w.get("bookingPointsTotal", 0.0) or (a_ext_w.get("cardsTotal", 0.0) * 10.0)
    team_avg_booking = bp_dom + bp_ext
    if h2h_booking:
        avg_booking = sum(h2h_booking) / len(h2h_booking)
    elif team_avg_booking > 0:
        avg_booking = team_avg_booking


    # ══════════════════════════════════════════════════════════════
    # BARÈME V3 PENALTY /100 — Régularisation bayésienne + Interaction Obt/Conc
    # ══════════════════════════════════════════════════════════════
    LEAGUE_PEN_RATES_V3 = {
        "copa libertadores": 0.33, "copa sudamericana": 0.30,
        "premier league": 0.32,    "ligue 1": 0.29,
        "bundesliga": 0.27,        "serie a": 0.31,
        "la liga": 0.29,           "laliga": 0.29,
        "champions league": 0.27,  "championsleague": 0.27,
        "superliga": 0.31,         "brasileirao": 0.32,
        "liga betplay": 0.29,      "primeira liga": 0.30,
    }

    mu_league = 0.245  # moyenne globale par défaut
    # ponytail: unibet_league contient le vrai nom ("copa libertadores", "bundesliga"…)
    # AdamChoi renvoie des codes internes (CLI1, UCL1…) inutilisables ici
    league_lc = (unibet_league or league or "").lower()
    for _k, _v in LEAGUE_PEN_RATES_V3.items():
        if _k in league_lc:
            mu_league = _v
            break

    # V3 Pilier 1 : Arbitre régularisé bayésien /25 (k=6 matchs de prior)
    if ref_is_known and total_games >= 0:
        k_prior = 6
        ratio_corr_v3 = (pen_per_match * total_games + k_prior * mu_league) / (total_games + k_prior) if (total_games + k_prior) > 0 else mu_league
        if ratio_corr_v3 >= 0.50: v3_p1 = 25
        elif ratio_corr_v3 >= 0.40: v3_p1 = 22
        elif ratio_corr_v3 >= 0.35: v3_p1 = 19
        elif ratio_corr_v3 >= 0.30: v3_p1 = 16
        elif ratio_corr_v3 >= 0.25: v3_p1 = 11
        elif ratio_corr_v3 >= 0.20: v3_p1 = 6
        else: v3_p1 = max(0, round(ratio_corr_v3 / 0.20 * 3))
    else:
        ratio_corr_v3 = 0.0
        v3_p1 = 0

    # V3 Pilier 2 : Interaction Obtenus × Concédés /30
    signal_dom = obt_dom + cnc_ext
    signal_ext = obt_ext + cnc_dom
    def _v3_signal_pts(s):
        if s >= 7: return 15
        elif s >= 5: return 12
        elif s >= 4: return 9
        elif s >= 3: return 6
        elif s >= 2: return 3
        elif s >= 1: return 1
        return 0
    v3_p2_base = _v3_signal_pts(signal_dom) + _v3_signal_pts(signal_ext)
    v3_bonus_ds = 6 if (signal_dom >= 2 and signal_ext >= 2) else (3 if (signal_dom >= 3 or signal_ext >= 3) else 0)
    v3_p2 = min(30, v3_p2_base + v3_bonus_ds)
    v3_peno_status = "DOUBLE_SIGNAL" if (signal_dom >= 2 and signal_ext >= 2) else (
        "VALIDE" if (signal_dom >= 1 or signal_ext >= 1) else "FAIBLE")

    # V3 Pilier 3 : Danger Surface /25 (SOT 12 + IPO 8 + Fouls proxy 5)
    if sot_comb >= 13.0: v3_p3_sot = 12
    elif sot_comb >= 11.0: v3_p3_sot = 10
    elif sot_comb >= 9.0: v3_p3_sot = 8
    elif sot_comb >= 7.0: v3_p3_sot = 5
    elif sot_comb >= 5.0: v3_p3_sot = 3
    else: v3_p3_sot = 1
    if ipo_comb >= 3.5: v3_p3_ipo = 8
    elif ipo_comb >= 3.0: v3_p3_ipo = 6
    elif ipo_comb >= 2.5: v3_p3_ipo = 4
    elif ipo_comb >= 1.5: v3_p3_ipo = 2
    else: v3_p3_ipo = 1
    if avg_booking >= 60: v3_p3_fouls = 5
    elif avg_booking >= 45: v3_p3_fouls = 3
    elif avg_booking >= 30: v3_p3_fouls = 2
    else: v3_p3_fouls = 1
    v3_p3 = min(25, v3_p3_sot + v3_p3_ipo + v3_p3_fouls)

    # V3 Pilier 4 : Intensité xG /10 (décorrélé du Pilier 3)
    xg_proxy = xg_total if xg_total > 0 else tot_goals_avg
    if xg_proxy >= 5.0: v3_p4 = 10
    elif xg_proxy >= 4.0: v3_p4 = 8
    elif xg_proxy >= 3.0: v3_p4 = 6
    elif xg_proxy >= 2.0: v3_p4 = 4
    else: v3_p4 = 2

    # V3 Pilier 5 : Tension Cartons Récents /5
    if avg_booking >= 65: v3_p5 = 5
    elif avg_booking >= 50: v3_p5 = 4
    elif avg_booking >= 35: v3_p5 = 3
    elif avg_booking >= 20: v3_p5 = 2
    else: v3_p5 = 1

    # V3 Pilier 6 : Ligue & VAR & Contexte /5
    LEAGUE_VAR_V3 = {"premier league","ligue 1","bundesliga","serie a","la liga","laliga",
                     "champions league","championsleague","copa libertadores","copa sudamericana",
                     "brasileirao","superliga","premier liga"}
    v3_p6_ligue = 3 if mu_league >= 0.30 else (2 if mu_league >= 0.26 else 1)
    v3_p6_var   = 2 if any(_k in league_lc for _k in LEAGUE_VAR_V3) else 0
    v3_p6 = min(5, v3_p6_ligue + v3_p6_var)

    score_penalty_v3 = max(0, min(100, v3_p1 + v3_p2 + v3_p3 + v3_p4 + v3_p5 + v3_p6))
    eligible_v3 = ref_is_known and ratio_corr_v3 >= 0.30 and score_penalty_v3 >= 80
    pts_ipo = o25_b1
    pts_goals = o25_b2
    pts_freq = o25_b3
    pts_sot = o25_b4
    pts_ha = o25_b5
    pts_league = o25_b6
    avg_freq_ha = comb_o25_pct

    if is_batch:
        return {
            "team_a": team_a,
            "team_b": team_b,
            "league": league,
            "score": total_score,
            "classe": classe,
            "prob": round(total_score * 0.78, 1),
            "pts_ipo": pts_ipo, "ipo_comb": round(ipo_comb, 2),
            "pts_goals": pts_goals, "total_goals_brut": round(total_goals_brut, 1),
            "pts_freq": pts_freq, "avg_freq_all": round(o25_avg_rate, 1),
            "pts_sot": pts_sot, "sot_comb": round(sot_comb, 1),
            "pts_ha": pts_ha, "avg_freq_ha": round(avg_freq_ha, 1),
            "pts_league": pts_league,
            "xg_total": round(xg_total, 2),
            "sot_total": round(sot_total, 1),
            "verdict": verdict,
            "red_flags": red_flags,
            "recent_h_dom": recent_h_dom[:10],
            "recent_a_ext": recent_a_ext[:10],
            "freq_o15": freq_o15,
            "freq_btts": freq_btts,
            "score_o15": score_o15,
            "score_btts": score_btts,
            "score_penalty": score_penalty,
            "pts_pen_ref": pts_pen_arb,
            "pts_pen_sot": pts_pen_teams,
            "pts_pen_cards": pts_pen_cards,
            "pts_pen_goals": pts_pen_goals,
            "ref_name": ref_name,
            "ref_status": ref_status,
            "pen_per_match": round(pen_per_match, 3),
            "avg_booking": round(avg_booking, 1),
            "peno_badge": peno_badge,
            "peno_status": peno_status,
            "p_dom_10m": p_dom_10m,
            "p_ext_10m": p_ext_10m,
            "p_tot_10m": p_tot_10m,
            # ── Champs V3 ──
            "score_penalty_v3": score_penalty_v3,
            "eligible_v3": eligible_v3,
            "v3_p1_ref": v3_p1,
            "v3_p2_peno": v3_p2,
            "v3_p3_surface": v3_p3,
            "v3_p4_intensity": v3_p4,
            "v3_p5_tension": v3_p5,
            "v3_p6_league": v3_p6,
            "ratio_corr_v3": round(ratio_corr_v3, 3),
            "v3_peno_status": v3_peno_status,
            "obt_dom": obt_dom, "cnc_dom": cnc_dom,
            "obt_ext": obt_ext, "cnc_ext": cnc_ext,
            "signal_dom": signal_dom, "signal_ext": signal_ext,
        }



    print(f"⚽ {team_a.upper()} — {team_b.upper()}")
    print(f"\n🔥 SCORE OVER 2,5 : {total_score}/100")
    print(f"📊 CLASSEMENT : {classe}")
    print(f"🛡️ PROBABILITÉ STATISTIQUE : {round(total_score * 0.78, 1)} %\n")
    print(f"1. Potentiel offensif (IPO {ipo_comb:.2f}) : {pts_ipo}/25")
    print(f"2. Buts marqués/encaissés ({total_goals_brut:.1f}b) : {pts_goals}/15")
    print(f"3. Historique Over 2,5 ({o25_avg_rate:.0f}%) : {pts_freq}/20")
    print(f"4. Tirs cadrés ({sot_comb:.1f}t) : {pts_sot}/10")
    print(f"5. Home/Away ({avg_freq_ha:.0f}%) : {pts_ha}/20")
    print(f"6. Ligue : {pts_league}/10")
    print(f"\nTOTAL : {total_score}/100\n")

    print(f"### POTENTIEL ÉQUIPE A ({team_a} à Domicile)")
    print(f"• Buts marqués domicile : {gf_a:.1f}/match")
    print(f"• xG domicile implicite : {xg_a:.2f}")
    print(f"• Tirs cadrés produits : {sot_a:.1f}/match")
    print(f"• Défense adverse / buts encaissés extérieur : {ga_b:.1f}/match")
    print(f"• Tirs cadrés concédés par l'adversaire : {sota_b:.1f}/match")

    print(f"\n### POTENTIEL ÉQUIPE B ({team_b} à l'Extérieur)")
    print(f"• Buts marqués extérieur : {gf_b:.1f}/match")
    print(f"• xG extérieur implicite : {xg_b:.2f}")
    print(f"• Tirs cadrés produits : {sot_b:.1f}/match")
    print(f"• Défense adverse / buts encaissés domicile : {ga_a:.1f}/match")
    print(f"• Tirs cadrés concédés par l'adversaire : {sota_a:.1f}/match")

    print("\n### CONVERGENCES")
    if convergences:
        for c in convergences: print(f"✅ {c}")
    else: print("ℹ️ Aucune convergence multi-signaux majeure identifiée.")

    print("\n### DOUBLE SIGNAUX")
    if ds_a: print(f"✅ DOUBLE SIGNAL ÉQUIPE A ({team_a}) : Attaque domicile forte + Défense adverse fragile")
    else: print(f"❌ Pas de Double Signal complet pour l'Équipe A ({team_a})")

    if ds_b: print(f"✅ DOUBLE SIGNAL ÉQUIPE B ({team_b}) : Attaque extérieure productive + Défense adverse permissive")
    else: print(f"❌ Pas de Double Signal complet pour l'Équipe B ({team_b})")

    print("\n### RED FLAGS")
    if red_flags:
        for rf in red_flags: print(f"⚠️ RED FLAG : {rf}")
    else: print("✅ Aucun Red Flag majeur détecté.")

    print("\n### 📜 10 DERNIERS SCORES À DOMICILE — " + team_a.upper())
    for m in recent_h_dom[:10]:
        dt = m.get("date", "N/A")
        opp = m.get("vs", m.get("awayTeam", "Adversaire"))
        hg = m.get("homeGoals", m.get("homeGoalsFt", 0))
        ag = m.get("awayGoals", m.get("awayGoalsFt", 0))
        tot = int(hg) + int(ag)
        icon = "🔥 3+ buts" if tot >= 3 else "⚪ < 3 buts"
        print(f"  • {dt} vs {opp:<20} | Score : {hg}-{ag} ({tot} buts) [{icon}]")

    print("\n### 📜 10 DERNIERS SCORES À L'EXTÉRIEUR — " + team_b.upper())
    for m in recent_a_ext[:10]:
        dt = m.get("date", "N/A")
        opp = m.get("vs", m.get("homeTeam", "Adversaire"))
        hg = m.get("homeGoals", m.get("homeGoalsFt", 0))
        ag = m.get("awayGoals", m.get("awayGoalsFt", 0))
        tot = int(hg) + int(ag)
        icon = "🔥 3+ buts" if tot >= 3 else "⚪ < 3 buts"
        print(f"  • {dt} vs {opp:<20} | Score : {hg}-{ag} ({tot} buts) [{icon}]")

    print("\n### VERDICT FINAL")
    print(f"{verdict}\n")

def parse_line(line):
    line = re.sub(r'^\d{1,2}:\d{2}\s*', '', line.strip())
    for sep in [" vs ", " v ", " contre ", " - ", " / ", " – ", " — "]:
        if sep in line.lower():
            parts = line.lower().split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    words = line.strip().split()
    if len(words) == 2:
        return words[0], words[1]
    if len(words) == 4:
        return f"{words[0]} {words[1]}", f"{words[2]} {words[3]}"
    if len(words) == 3:
        return f"{words[0]} {words[1]}", words[2]
    return None, None

def process_batch_lines(lines):
    matches_list = []
    for line in lines:
        if not line.strip(): continue
        h, a = parse_line(line)
        if h and a:
            matches_list.append((h, a))

    if not matches_list:
        print("⚠️ Aucun match valide détecté dans votre copier-coller.")
        return

    print(f"\n================================================================================")
    print(f"📊 CLASSEMENT BATCH ({len(matches_list)} MATCHS ANALYSÉS EN PARALLÈLE)")
    print(f"================================================================================")
    fx_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(analyze_pure_stats_20, h, a, fx_data, True) for h, a in matches_list]
        for f in futs:
            try:
                res = f.result()
                if res: results.append(res)
            except Exception: pass

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, res in enumerate(results, 1):
        rf_str = f" | ⚠️ {', '.join(res['red_flags'])}" if res['red_flags'] else ""
        print(f"#{i:02d} {res['team_a'].upper()} vs {res['team_b'].upper()} ({res['league']}) — SCORE: {res['score']}/100 | Prob: {res['prob']}%")
        print(f"     VERDICT: {res['verdict']}{rf_str}")
    print("================================================================================\n")

def interactive_paste_mode():
    print("📋 MODE COPIER-COLLER INTERACTIF POWERSHELL")
    print("Collez votre liste de matchs ci-dessous (un match par ligne).")
    print("👉 Appuyez sur ENTRÉE DEUX FOIS lorsque vous avez fini de coller :\n")
    
    lines = []
    while True:
        try:
            line = input()
            if not line.strip():
                break
            lines.append(line.strip())
        except EOFError:
            break
            
    if lines:
        process_batch_lines(lines)

def parse_cli_args():
    if len(sys.argv) <= 1:
        return None, None
    args = sys.argv[1:]
    if len(args) == 2:
        return args[0], args[1]
    full_str = " ".join(args)
    for sep in [" vs ", " v ", " contre ", " - ", " / ", " – ", " — "]:
        if sep in full_str.lower():
            parts = full_str.lower().split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    if len(args) == 4:
        return f"{args[0]} {args[1]}", f"{args[2]} {args[3]}"
    if len(args) == 3:
        return f"{args[0]} {args[1]}", args[2]
    return args[0], " ".join(args[1:])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        filepath = sys.argv[2] if len(sys.argv) > 2 else "matches.txt"
        if not os.path.exists(filepath):
            print(f"❌ Fichier '{filepath}' introuvable.")
            sys.exit(0)
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        process_batch_lines(lines)

    elif len(sys.argv) > 1 and sys.argv[1] == "--today":
        print("\n================================================================================")
        print("📊 CLASSEMENT AUTOMATIQUE DE TOUS LES MATCHS DU JOUR (PARALLÈLE)")
        print("================================================================================")
        fx_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
        matches_list = []
        for d in fx_data.get("dates", [])[:1]:
            for lg in d.get("leagues", []):
                for fx in lg.get("fixtures", []):
                    matches_list.append((fx["hometeam"], fx["awayteam"]))
        results = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(analyze_pure_stats_20, h, a, fx_data, True) for h, a in matches_list]
            for f in futs:
                try:
                    res = f.result()
                    if res and res["score"] >= 50: results.append(res)
                except Exception: pass
        results.sort(key=lambda x: x["score"], reverse=True)
        for i, res in enumerate(results, 1):
            rf_str = f" | ⚠️ {', '.join(res['red_flags'])}" if res['red_flags'] else ""
            print(f"#{i:02d} {res['team_a'].upper()} vs {res['team_b'].upper()} ({res['league']}) — SCORE: {res['score']}/100 | Prob: {res['prob']}%")
            print(f"     VERDICT: {res['verdict']}{rf_str}")
        print("================================================================================\n")

    elif len(sys.argv) > 1 and sys.argv[1] == "--paste":
        interactive_paste_mode()

    elif len(sys.argv) == 1:
        interactive_paste_mode()

    else:
        home, away = parse_cli_args()
        if home and away:
            analyze_pure_stats_20(home, away)
        else:
            interactive_paste_mode()
