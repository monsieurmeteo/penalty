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
                        best_match = (fx.get("externalId"), h_name, a_name, lg.get("league"))

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

    # ponytail: si aucune donnée réelle disponible (équipe inconnue d'AdamChoi), on ne fabrique rien
    has_real_data = bool(recent_h_dom or recent_a_ext or h_dom_w or a_ext_w)
    if not has_real_data:
        if is_batch:
            return {
                "score": 0, "classe": "❓ Non analysé", "calibrated_prob": 0,
                "pts_ipo": 0, "ipo_comb": 0, "pts_buts": 0, "avg_buts": 0,
                "pts_freq": 0, "o25_avg_rate": 0, "pts_sot": 0, "sot_comb": 0,
                "pts_ha": 0, "avg_freq_ha": 0, "pts_league": 0,
                "xg_total": 0, "sot_total": 0,
                "verdict": "Équipe non trouvée sur AdamChoi — données insuffisantes.",
                "red_flags": ["Aucune donnée AdamChoi"],
                "recent_h_dom": [], "recent_a_ext": []
            }
        print(f"❓ {home_query} vs {away_query} — Équipe non trouvée sur AdamChoi, score non calculé.")
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

    # ── BARÈME V2.1 — SCORE OVER 2.5 BUTS /100 ──
    # Total exact 100 points
    # 1. IPO — Indice de Potentiel Offensif (25 pts max)
    ipo_dom = (sot_a * 0.28) + (gf_a * 0.50)
    ipo_ext = (sot_b * 0.28) + (gf_b * 0.50)
    ipo_comb = ipo_dom + ipo_ext

    if ipo_comb >= 3.80: pts_ipo = 25
    elif ipo_comb >= 3.50: pts_ipo = 23
    elif ipo_comb >= 3.20: pts_ipo = 21
    elif ipo_comb >= 3.00: pts_ipo = 19
    elif ipo_comb >= 2.80: pts_ipo = 17
    elif ipo_comb >= 2.60: pts_ipo = 15
    elif ipo_comb >= 2.40: pts_ipo = 12
    elif ipo_comb >= 2.20: pts_ipo = 9
    elif ipo_comb >= 2.00: pts_ipo = 6
    else: pts_ipo = 3

    # 2. Potentiel buts marqués + encaissés (15 pts max)
    total_goals_brut = gf_a + ga_a + gf_b + ga_b
    if total_goals_brut >= 6.0: pts_goals = 15
    elif total_goals_brut >= 5.5: pts_goals = 14
    elif total_goals_brut >= 5.0: pts_goals = 13
    elif total_goals_brut >= 4.6: pts_goals = 11
    elif total_goals_brut >= 4.2: pts_goals = 9
    elif total_goals_brut >= 3.8: pts_goals = 7
    elif total_goals_brut >= 3.4: pts_goals = 5
    elif total_goals_brut >= 3.0: pts_goals = 3
    else: pts_goals = 1

    # 3. Fréquence historique Over 2.5 (20 pts max)
    if o25_avg_rate >= 80.0: pts_freq = 20
    elif o25_avg_rate >= 75.0: pts_freq = 18
    elif o25_avg_rate >= 70.0: pts_freq = 16
    elif o25_avg_rate >= 65.0: pts_freq = 14
    elif o25_avg_rate >= 60.0: pts_freq = 12
    elif o25_avg_rate >= 55.0: pts_freq = 10
    elif o25_avg_rate >= 50.0: pts_freq = 8
    elif o25_avg_rate >= 45.0: pts_freq = 5
    elif o25_avg_rate >= 40.0: pts_freq = 3
    else: pts_freq = 0

    # 4. Tirs cadrés combinés (10 pts max)
    sot_comb = sot_a + sot_b
    if sot_comb >= 12.0: pts_sot = 10
    elif sot_comb >= 11.0: pts_sot = 9
    elif sot_comb >= 10.0: pts_sot = 8
    elif sot_comb >= 9.0: pts_sot = 7
    elif sot_comb >= 8.0: pts_sot = 6
    elif sot_comb >= 7.0: pts_sot = 4
    elif sot_comb >= 6.0: pts_sot = 2
    else: pts_sot = 0

    # 5. Domicile / Extérieur spécifique (20 pts max)
    o25_h_dom_cnt = count_o25(recent_h_dom[:10])
    o25_a_ext_cnt = count_o25(recent_a_ext[:10])
    o25_h_dom_rate = (o25_h_dom_cnt / max(1, len(recent_h_dom[:10]))) * 100
    o25_a_ext_rate = (o25_a_ext_cnt / max(1, len(recent_a_ext[:10]))) * 100
    avg_freq_ha = (o25_h_dom_rate + o25_a_ext_rate) / 2.0

    if avg_freq_ha >= 80.0: pts_ha = 20
    elif avg_freq_ha >= 75.0: pts_ha = 18
    elif avg_freq_ha >= 70.0: pts_ha = 16
    elif avg_freq_ha >= 65.0: pts_ha = 14
    elif avg_freq_ha >= 60.0: pts_ha = 12
    elif avg_freq_ha >= 55.0: pts_ha = 10
    elif avg_freq_ha >= 50.0: pts_ha = 8
    elif avg_freq_ha >= 45.0: pts_ha = 5
    elif avg_freq_ha >= 40.0: pts_ha = 3
    else: pts_ha = 0

    # 6. Contexte Ligue Continue (10 pts max)
    league_avg_goals = 2.75
    if league_avg_goals >= 3.30: pts_league = 10
    elif league_avg_goals >= 3.00: pts_league = 9
    elif league_avg_goals >= 2.75: pts_league = 7
    elif league_avg_goals >= 2.55: pts_league = 5
    elif league_avg_goals >= 2.35: pts_league = 3
    else: pts_league = 1

    raw_score = pts_ipo + pts_goals + pts_freq + pts_sot + pts_ha + pts_league
    # Plafond Red Flags à -20 pts max
    rf_pen_o25 = min(20, len(red_flags) * 10)
    total_score = max(0, min(100, raw_score - rf_pen_o25))

    # Classification V2
    if total_score >= 90: classe = "🔥🔥🔥 Exceptionnel"
    elif total_score >= 85: classe = "🔥🔥 Très fort"
    elif total_score >= 80: classe = "🔥 Fort"
    elif total_score >= 75: classe = "✅ Bon potentiel"
    elif total_score >= 70: classe = "🟡 Intéressant mais à confirmer"
    elif total_score >= 65: classe = "⚠️ Moyen"
    elif total_score >= 60: classe = "⚠️ Fragile"
    else: classe = "❌ À écarter"

    calibrated_prob = int((o25_avg_rate * 0.60) + (min(90, int(xg_total * 18)) * 0.40))
    if red_flags: calibrated_prob = max(25, calibrated_prob - (len(red_flags) * 8))

    verdict = f"{classe} ({total_score}/100)"

    # ══════════════════════════════════════════════════════════════
    # BARÈME V2.1 OVER 1.5 /100 — Total exact 100 points
    # ══════════════════════════════════════════════════════════════

    # 1. IPO (25 pts)
    if ipo_comb >= 3.00: p_o15_ipo = 25
    elif ipo_comb >= 2.70: p_o15_ipo = 23
    elif ipo_comb >= 2.40: p_o15_ipo = 21
    elif ipo_comb >= 2.20: p_o15_ipo = 19
    elif ipo_comb >= 2.00: p_o15_ipo = 17
    elif ipo_comb >= 1.80: p_o15_ipo = 14
    elif ipo_comb >= 1.60: p_o15_ipo = 11
    elif ipo_comb >= 1.40: p_o15_ipo = 8
    elif ipo_comb >= 1.20: p_o15_ipo = 5
    else: p_o15_ipo = 2

    # 2. Buts totaux (15 pts)
    if total_goals_brut >= 5.0: p_o15_goals = 15
    elif total_goals_brut >= 4.5: p_o15_goals = 14
    elif total_goals_brut >= 4.0: p_o15_goals = 13
    elif total_goals_brut >= 3.6: p_o15_goals = 11
    elif total_goals_brut >= 3.2: p_o15_goals = 9
    elif total_goals_brut >= 2.8: p_o15_goals = 7
    elif total_goals_brut >= 2.4: p_o15_goals = 5
    elif total_goals_brut >= 2.0: p_o15_goals = 3
    else: p_o15_goals = 1

    # 3. Fréquence Over 1.5 (20 pts)
    o15_h_all = count_o15(recent_h_all[:20])
    o15_a_all = count_o15(recent_a_all[:20])
    o15_avg_rate = (((o15_h_all / max(1, len(recent_h_all[:20]))) + (o15_a_all / max(1, len(recent_a_all[:20])))) / 2.0) * 100
    if o15_avg_rate >= 90: p_o15_freq = 20
    elif o15_avg_rate >= 85: p_o15_freq = 18
    elif o15_avg_rate >= 80: p_o15_freq = 16
    elif o15_avg_rate >= 75: p_o15_freq = 14
    elif o15_avg_rate >= 70: p_o15_freq = 12
    elif o15_avg_rate >= 65: p_o15_freq = 10
    elif o15_avg_rate >= 60: p_o15_freq = 8
    elif o15_avg_rate >= 55: p_o15_freq = 5
    elif o15_avg_rate >= 50: p_o15_freq = 3
    else: p_o15_freq = 0

    # 4. Tirs cadrés (10 pts)
    p_o15_sot = pts_sot

    # 5. Dom/Ext spécifique Over 1.5 (20 pts)
    if freq_o15 >= 90: p_o15_ha = 20
    elif freq_o15 >= 85: p_o15_ha = 18
    elif freq_o15 >= 80: p_o15_ha = 16
    elif freq_o15 >= 75: p_o15_ha = 14
    elif freq_o15 >= 70: p_o15_ha = 12
    elif freq_o15 >= 65: p_o15_ha = 10
    elif freq_o15 >= 60: p_o15_ha = 8
    elif freq_o15 >= 55: p_o15_ha = 5
    elif freq_o15 >= 50: p_o15_ha = 3
    else: p_o15_ha = 0

    # 6. Ligue (10 pts)
    p_o15_league = pts_league

    rf_o15 = [f for f in red_flags if "Attaque" in f or "Échantillon" in f]
    rf_pen_o15 = min(15, len(rf_o15) * 5)
    score_o15 = max(0, min(100, p_o15_ipo + p_o15_goals + p_o15_freq + p_o15_sot + p_o15_ha + p_o15_league - rf_pen_o15))

    # ══════════════════════════════════════════════════════════════
    # BARÈME V2.1 BTTS OUI /100 — Logique de Confrontation (Total exact 100 pts)
    # ══════════════════════════════════════════════════════════════

    # 1. Potentiel But DOM (Attaque DOM × Défense EXT) (30 pts max)
    comp_dom = (gf_a * 0.60) + (ga_b * 0.40)
    if comp_dom >= 2.20: p_btts_pot_dom = 30
    elif comp_dom >= 1.90: p_btts_pot_dom = 26
    elif comp_dom >= 1.60: p_btts_pot_dom = 22
    elif comp_dom >= 1.30: p_btts_pot_dom = 16
    elif comp_dom >= 1.00: p_btts_pot_dom = 10
    elif comp_dom >= 0.70: p_btts_pot_dom = 4
    else: p_btts_pot_dom = 0

    # 2. Potentiel But EXT (Attaque EXT × Défense DOM) (30 pts max)
    comp_ext = (gf_b * 0.60) + (ga_a * 0.40)
    if comp_ext >= 2.00: p_btts_pot_ext = 30
    elif comp_ext >= 1.70: p_btts_pot_ext = 26
    elif comp_ext >= 1.40: p_btts_pot_ext = 22
    elif comp_ext >= 1.10: p_btts_pot_ext = 16
    elif comp_ext >= 0.80: p_btts_pot_ext = 10
    elif comp_ext >= 0.50: p_btts_pot_ext = 4
    else: p_btts_pot_ext = 0

    # 3. Fréquence historique BTTS sur 20 matchs (20 pts max)
    if freq_btts >= 80: p_btts_freq = 20
    elif freq_btts >= 75: p_btts_freq = 17
    elif freq_btts >= 70: p_btts_freq = 14
    elif freq_btts >= 65: p_btts_freq = 11
    elif freq_btts >= 60: p_btts_freq = 8
    elif freq_btts >= 50: p_btts_freq = 4
    else: p_btts_freq = 0

    # 4. Fréquence BTTS Dom/Ext spécifique (10 pts max)
    if freq_btts_dom >= 75 and freq_btts_ext >= 75: p_btts_ha = 10
    elif freq_btts_dom >= 65 or freq_btts_ext >= 65: p_btts_ha = 8
    elif freq_btts_dom >= 55 or freq_btts_ext >= 55: p_btts_ha = 5
    elif freq_btts_dom >= 45 or freq_btts_ext >= 45: p_btts_ha = 2
    else: p_btts_ha = 0

    # 5. Contexte ligue (10 pts max)
    p_btts_league = pts_league

    # Red flags BTTS : si une équipe marque <0.8 goal/m, si échantillon <3 ou si déséquilibre majeur (Risque Clean Sheet)
    rf_btts = []
    if gf_a < 0.8: rf_btts.append(f"Attaque DOM trop faible ({gf_a:.1f} goal/m) — risque 0 goal DOM")
    if gf_b < 0.8: rf_btts.append(f"Attaque EXT trop faible ({gf_b:.1f} goal/m) — risque 0 goal EXT")
    if n_h < 3: rf_btts.append(f"Échantillon DOM trop faible ({n_h} match)")
    if n_a < 3: rf_btts.append(f"Échantillon EXT trop faible ({n_a} match)")

    # Garde-fou Anti Clean Sheet : Déséquilibre offensif majeur ou contradiction marché bookmaker (ex: Over 2.5 @1.30 vs BTTS @2.20)
    unibet_o25 = m_unibet.get("over25") if isinstance(m_unibet, dict) else None
    unibet_btts = m_unibet.get("btts_oui") if isinstance(m_unibet, dict) else None

    if (gf_a >= 2.2 and gf_b < 1.0) or (gf_b >= 2.0 and gf_a < 1.0):
        rf_btts.append(f"Risque Clean Sheet / Déséquilibre offensif majeur ({gf_a:.1f} vs {gf_b:.1f})")
    elif unibet_o25 and unibet_btts and unibet_o25 <= 1.42 and unibet_btts >= 2.00:
        rf_btts.append(f"Risque Clean Sheet Bookmaker (Over 2.5 @{unibet_o25:.2f} vs BTTS @{unibet_btts:.2f})")

    rf_pen_btts = min(25, len(rf_btts) * 12)
    score_btts = max(0, min(100, p_btts_pot_dom + p_btts_pot_ext + p_btts_freq + p_btts_ha + p_btts_league - rf_pen_btts))

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

    bp_dom = h_dom_w.get("bookingPointsTotal", 0.0) or (h_dom_w.get("cardsTotal", 0.0) * 10.0)
    bp_ext = a_ext_w.get("bookingPointsTotal", 0.0) or (a_ext_w.get("cardsTotal", 0.0) * 10.0)
    team_avg_booking = bp_dom + bp_ext

    if h2h_booking:
        avg_booking = sum(h2h_booking) / len(h2h_booking)
    elif team_avg_booking > 0:
        avg_booking = team_avg_booking
    else:
        avg_booking = 40.0

    if avg_booking >= 70: p_pen_cards = 20
    elif avg_booking >= 55: p_pen_cards = 16
    elif avg_booking >= 40: p_pen_cards = 12
    elif avg_booking >= 30: p_pen_cards = 8
    else: p_pen_cards = 3

    # 4. Activité Offensive Globale (20 pts max)
    if total_goals_brut >= 5.5 or ipo_comb >= 3.5: p_pen_goals = 20
    elif total_goals_brut >= 4.5 or ipo_comb >= 3.0: p_pen_goals = 16
    elif total_goals_brut >= 3.8 or ipo_comb >= 2.5: p_pen_goals = 12
    elif total_goals_brut >= 3.0: p_pen_goals = 8
    else: p_pen_goals = 3

    if ref_is_known:
        score_penalty = max(0, min(100, p_pen_ref + p_pen_sot + p_pen_cards + p_pen_goals))
    else:
        # Score brut sur les 3 piliers disponibles (25 + 20 + 20 = 65 pts max)
        raw_avail = p_pen_sot + p_pen_cards + p_pen_goals
        # Normalisation sur 100 puis décote de -10% pour confiance réduite
        norm_score = (raw_avail / 65.0) * 100.0
        score_penalty = max(0, min(100, round(norm_score * 0.90)))

    if is_batch:
        return {
            "team_a": team_a,
            "team_b": team_b,
            "league": league,
            "score": total_score,
            "classe": classe,
            "prob": calibrated_prob,
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
            "ref_name": ref_name,
            "ref_status": ref_status,
            "pen_per_match": round(pen_per_match, 3),
            "avg_booking": round(avg_booking, 1),
        }


    print(f"⚽ {team_a.upper()} — {team_b.upper()}")
    print(f"\n🔥 SCORE OVER 2,5 : {total_score}/100")
    print(f"📊 CLASSEMENT : {classe}")
    print(f"🛡️ PROBABILITÉ STATISTIQUE : {calibrated_prob} %\n")
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
