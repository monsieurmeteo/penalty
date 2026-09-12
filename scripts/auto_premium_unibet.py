import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import email.policy
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formatdate

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ── Seuils Stratégie Favoris Win & 2 Buts d'Avance (Early Payout) ───────────
MAX_COTE_FAV           = 2.20  # Cote maximale du favori Unibet 1N2
MIN_COTE_FAV           = 1.30  # Plancher optimisé : accepte les favoris solides dès 1.30
MIN_SCORE_FAV_RETAINED = 50    # Score Domination minimal (Bronze dès 50/100)
MIN_SCORE_FAV_SOLID    = 75    # Score AdamChoi pour être qualifié Favori Solide (Or / Platine)

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}

COUNTRIES = [
    "france", "angleterre", "espagne", "italie", "allemagne", "portugal", "pays-bas",
    "belgique", "ecosse", "suisse", "autriche", "turquie", "grece", "pologne", "croatie",
    "serbie", "roumanie", "ukraine", "rep-tcheque", "republique-tcheque", "hongrie", "bulgarie", "slovaquie",
    "suede", "norvege", "danemark", "finlande", "irlande", "islande", "lettonie", "lituanie", "estonie",
    "bosnie-herzeg", "georgie",
    "bresil", "argentine", "colombie", "mexique", "chili", "equateur", "paraguay", "uruguay", "amerique", "etats-unis", "usa", "canada",
    "japon", "coree-du-sud", "australie", "coupes-d-europe", "international",
    "afrique-du-sud", "arabie-saoudite", "emirats-arabes-unis", "egypte", "maroc", "algerie", "tunisie",
    "chine", "inde", "israel", "perou", "bolivie", "venezuela", "costa-rica", "honduras", "guatemala"
]

def format_french_date(iso_str):
    if not iso_str: return "À venir"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        days = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
        day_name = days[dt.weekday()]
        return dt.strftime(f"{day_name} %d/%m à %HH%M").replace("H", "h")
    except Exception:
        return iso_str

def _get_session_day(m):
    """
    ponytail: Détermine la session sportive du match (06h00 du matin à 06h00 le lendemain).
    Rattache automatiquement les matchs de nuit (00h-05h59) à la session de la veille au soir.
    Garantit des combinés strictement Jour par Jour (Option 1).
    """
    if not m: return ""
    start_iso = m.get("start_iso")
    if start_iso:
        try:
            if ZoneInfo:
                dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Paris"))
            else:
                dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
            return (dt - timedelta(hours=6)).strftime("%Y-%m-%d")
        except Exception:
            pass
    t = m.get("time", m.get("date_str", ""))
    if " à " in t:
        d_p, h_p = t.split(" à ", 1)
        try:
            h = int(h_p.split("h")[0])
            m_dm = re.search(r'(\d{1,2})/(\d{1,2})', d_p)
            if m_dm:
                day_val = int(m_dm.group(1))
                month_val = int(m_dm.group(2))
                year_val = datetime.now().year
                dt = datetime(year_val, month_val, day_val, h)
                return (dt - timedelta(hours=6)).strftime("%Y-%m-%d")
        except Exception:
            pass
        return d_p.strip()
    return t.strip()

def _clean_team_key(name):
    if not name: return ""
    n = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('ASCII').lower()
    return re.sub(r'[^a-z0-9]', '', n)

def is_night_match(m):
    """
    Retourne True si le match débute entre 00h01 et 06h00 (inclus).
    Règle d'or : exclusion stricte des matchs de nuit pour la Méthode 1 et la Méthode 2.
    """
    if not m:
        return False
    for field in ["time", "date_str", "minute"]:
        val = str(m.get(field, ""))
        mat = re.search(r'(?:à\s*|T)?(\d{1,2})[h:](\d{2})', val)
        if mat:
            hour = int(mat.group(1))
            minute = int(mat.group(2))
            mins = hour * 60 + minute
            if 1 <= mins <= 360:
                return True
    return False

# ── Moteur d'Analyse « Favori Win & 2 Buts d'Avance (Early Payout) » ────────
def evaluate_favorite_domination(m):
    c1, c2 = m.get("c1"), m.get("c2")
    if not c1 or not c2 or c1 <= 1.0 or c2 <= 1.0 or c1 == c2:
        return None

    is_dom = c1 < c2
    fav_odds = c1 if is_dom else c2
    dog_odds = c2 if is_dom else c1

    # ponytail: cote min 1.40 et max 2.20 pour éliminer les cotes faibles destructrices de capital
    if fav_odds < MIN_COTE_FAV or fav_odds > MAX_COTE_FAV:
        return None

    fav_team = m["dom"] if is_dom else m["ext"]
    dog_team = m["ext"] if is_dom else m["dom"]
    fav_side = "dom" if is_dom else "ext"

    rec_h = m.get("recent_h_dom", [])
    rec_a = m.get("recent_a_ext", [])
    fav_matches = rec_h if is_dom else rec_a
    dog_matches = rec_a if is_dom else rec_h

    if not fav_matches and not dog_matches:
        return None

    fav_wins, fav_lead2, fav_success, fav_cs = 0, 0, 0, 0
    fav_gf_tot, fav_ga_tot = 0, 0
    for match in fav_matches:
        gf = int(match.get("homeGoals", match.get("homeGoalsFt", 0)) if is_dom else match.get("awayGoals", match.get("awayGoalsFt", 0)))
        ga = int(match.get("awayGoals", match.get("awayGoalsFt", 0)) if is_dom else match.get("homeGoals", match.get("homeGoalsFt", 0)))
        gf_ht = int(match.get("homeGoalsHt", 0) if is_dom else match.get("awayGoalsHt", 0))
        ga_ht = int(match.get("awayGoalsHt", 0) if is_dom else match.get("homeGoalsHt", 0))

        win = (gf > ga) or (match.get("res") == "W")
        lead2 = (gf - ga >= 2) or (gf_ht - ga_ht >= 2)
        if win: fav_wins += 1
        if lead2: fav_lead2 += 1
        if win or lead2: fav_success += 1
        if ga == 0: fav_cs += 1
        fav_gf_tot += gf
        fav_ga_tot += ga

    n_fav = len(fav_matches) or 1
    pct_fav_win = round(fav_wins / n_fav * 100)
    pct_fav_lead2 = round(fav_lead2 / n_fav * 100)
    pct_fav_success = round(fav_success / n_fav * 100)
    pct_fav_cs = round(fav_cs / n_fav * 100)
    avg_fav_gf = round(fav_gf_tot / n_fav, 2)
    avg_fav_ga = round(fav_ga_tot / n_fav, 2)

    dog_losses, dog_trailed2, dog_no_goal = 0, 0, 0
    dog_gf_tot, dog_ga_tot = 0, 0
    for match in dog_matches:
        gf = int(match.get("awayGoals", match.get("awayGoalsFt", 0)) if is_dom else match.get("homeGoals", match.get("homeGoalsFt", 0)))
        ga = int(match.get("homeGoals", match.get("homeGoalsFt", 0)) if is_dom else match.get("awayGoals", match.get("awayGoalsFt", 0)))
        gf_ht = int(match.get("awayGoalsHt", 0) if is_dom else match.get("homeGoalsHt", 0))
        ga_ht = int(match.get("homeGoalsHt", 0) if is_dom else match.get("awayGoalsHt", 0))

        loss = (ga > gf) or (match.get("res") == "L")
        trailed2 = (ga - gf >= 2) or (ga_ht - gf_ht >= 2)
        if loss: dog_losses += 1
        if trailed2: dog_trailed2 += 1
        if gf == 0: dog_no_goal += 1
        dog_gf_tot += gf
        dog_ga_tot += ga

    n_dog = len(dog_matches) or 1
    pct_dog_loss = round(dog_losses / n_dog * 100)
    pct_dog_trailed2 = round(dog_trailed2 / n_dog * 100)
    pct_dog_no_goal = round(dog_no_goal / n_dog * 100)
    avg_dog_gf = round(dog_gf_tot / n_dog, 2)
    avg_dog_ga = round(dog_ga_tot / n_dog, 2)

    pts_fav = min(40, round((pct_fav_success * 0.35) + (pct_fav_cs * 0.05)))
    pts_dog = min(25, round((pct_dog_trailed2 * 0.15) + (pct_dog_loss * 0.10)))
    diff_goals = (avg_fav_gf - avg_fav_ga) + (avg_dog_ga - avg_dog_gf)
    pts_goals = max(0, min(20, round(10 + diff_goals * 3.5)))
    implied_prob = (1.0 / fav_odds) if fav_odds > 0 else 0
    pts_odds = min(15, round(implied_prob * 18))

    total_score = min(100, pts_fav + pts_dog + pts_goals + pts_odds)

    if total_score >= 85:
        badge = "💎 PLATINE"
        classe = "Ultra-Dominateur (Break quasi garanti)"
    elif total_score >= 75:
        badge = "🥇 OR"
        classe = "Très Solide (Forte probabilité 2 buts avance)"
    elif total_score >= 65:
        badge = "🥈 ARGENT"
        classe = "Supérieur (Avantage net)"
    elif total_score >= 50:
        badge = "🥉 BRONZE"
        classe = "Favorable (Bonne rentabilité)"
    else:
        badge = "⚠️ RISQUÉ"
        classe = "Incertain (Historique mitigé)"

    return {
        "fav_team": fav_team,
        "dog_team": dog_team,
        "fav_side": fav_side,
        "fav_odds": fav_odds,
        "dog_odds": dog_odds,
        "fav_score": total_score,
        "fav_badge": badge,
        "fav_classe": classe,
        "pct_fav_win": pct_fav_win,
        "pct_fav_lead2": pct_fav_lead2,
        "pct_fav_success": pct_fav_success,
        "pct_fav_cs": pct_fav_cs,
        "pct_dog_loss": pct_dog_loss,
        "pct_dog_trailed2": pct_dog_trailed2,
        "pct_dog_no_goal": pct_dog_no_goal,
        "avg_fav_gf": avg_fav_gf,
        "avg_dog_ga": avg_dog_ga,
        "pts_fav": pts_fav,
        "pts_dog": pts_dog,
        "pts_goals": pts_goals,
        "pts_odds": pts_odds,
        "n_fav": n_fav,
        "n_dog": n_dog,
        "market": "FAV_1N2",
        "market_label": "👑 Favori (+2b)"
    }

def evaluate_over15(m):
    """Désactivé : La méthode officielle repose à 100% sur les Favoris 1N2 (+2 Buts d'Avance)."""
    return None

def evaluate_btts(m):
    """Désactivé : La méthode officielle repose à 100% sur les Favoris 1N2 (+2 Buts d'Avance)."""
    return None

def render_fav_proof_html(m):
    fi = m.get("fav_info")
    if not fi or fi.get("market") in ["OVER_15", "BTTS"]:
        return ""
    fav_team = fi.get("fav_team", "")
    dog_team = fi.get("dog_team", "")
    is_dom = (fi.get("fav_side") == "dom")
    rec_fav = m.get("recent_h_dom", []) if is_dom else m.get("recent_a_ext", [])
    rec_dog = m.get("recent_a_ext", []) if is_dom else m.get("recent_h_dom", [])

    fav_pills = []
    for rm in rec_fav[:10]:
        hg = int(rm.get("homeGoals", rm.get("homeGoalsFt", 0)))
        ag = int(rm.get("awayGoals", rm.get("awayGoalsFt", 0)))
        hg_ht = int(rm.get("homeGoalsHt", 0))
        ag_ht = int(rm.get("awayGoalsHt", 0))
        gf = hg if is_dom else ag
        ga = ag if is_dom else hg
        gf_ht = hg_ht if is_dom else ag_ht
        ga_ht = ag_ht if is_dom else hg_ht
        win = (gf > ga) or (rm.get("res") == "W")
        lead2 = (gf - ga >= 2) or (gf_ht - ga_ht >= 2)
        s_txt = f"{hg}-{ag}"
        if lead2:
            fav_pills.append(f'<span style="background:#dcfce7; color:#15803d; font-weight:800; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #86efac; display:inline-block; margin:1px;">{s_txt} 👑 (+2)</span>')
        elif win:
            fav_pills.append(f'<span style="background:#f0fdf4; color:#166534; font-weight:700; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #bbf7d0; display:inline-block; margin:1px;">{s_txt} ✅</span>')
        elif gf == ga:
            fav_pills.append(f'<span style="background:#fef9c3; color:#854d0e; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #fef08a; display:inline-block; margin:1px;">{s_txt} ⏸️</span>')
        else:
            fav_pills.append(f'<span style="background:#fee2e2; color:#991b1b; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #fecaca; display:inline-block; margin:1px;">{s_txt} ❌</span>')
    fav_pills_html = " ".join(fav_pills) if fav_pills else '<span style="color:#94a3b8; font-style:italic;">Données indisponibles</span>'

    dog_pills = []
    for rm in rec_dog[:10]:
        hg = int(rm.get("homeGoals", rm.get("homeGoalsFt", 0)))
        ag = int(rm.get("awayGoals", rm.get("awayGoalsFt", 0)))
        hg_ht = int(rm.get("homeGoalsHt", 0))
        ag_ht = int(rm.get("awayGoalsHt", 0))
        gf = ag if is_dom else hg
        ga = hg if is_dom else ag
        gf_ht = ag_ht if is_dom else hg_ht
        ga_ht = hg_ht if is_dom else ag_ht
        loss = (ga > gf) or (rm.get("res") == "L")
        trailed2 = (ga - gf >= 2) or (ga_ht - gf_ht >= 2)
        s_txt = f"{hg}-{ag}"
        if trailed2:
            dog_pills.append(f'<span style="background:#fee2e2; color:#991b1b; font-weight:800; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #fca5a5; display:inline-block; margin:1px;">{s_txt} 💥 (-2)</span>')
        elif loss:
            dog_pills.append(f'<span style="background:#fff1f2; color:#be123c; font-weight:700; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #fecdd3; display:inline-block; margin:1px;">{s_txt} ❌</span>')
        elif gf == ga:
            dog_pills.append(f'<span style="background:#f8fafc; color:#64748b; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #e2e8f0; display:inline-block; margin:1px;">{s_txt} ⏸️</span>')
        else:
            dog_pills.append(f'<span style="background:#f0fdf4; color:#15803d; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #bbf7d0; display:inline-block; margin:1px;">{s_txt}</span>')
    dog_pills_html = " ".join(dog_pills) if dog_pills else '<span style="color:#94a3b8; font-style:italic;">Données indisponibles</span>'

    fav_loc = "Domicile" if is_dom else "Extérieur"
    dog_loc = "Extérieur" if is_dom else "Domicile"

    return f'''
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; margin-top:8px;">
        <div style="font-size:11px; color:#334155; line-height:1.6;">
            <div style="margin-bottom:6px;">
                <b>👑 10m {fav_team} ({fav_loc})</b> :<br>{fav_pills_html}
            </div>
            <div>
                <b>🛡️ 10m {dog_team} ({dog_loc})</b> :<br>{dog_pills_html}
            </div>
        </div>
    </div>
    '''

def get_unibet_active_games():
    print(f"Scraping Unibet France — {len(COUNTRIES)} catégories pays...")

    all_match_urls = set()

    def fetch_country(c):
        url = f"https://www.unibet.fr/paris-football/{c}"
        try:
            r = requests.get(url, headers=H, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                urls = set()
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if "/paris-football/" in href and "vs" in href and len(href.split("/")) >= 5:
                        full_url = f"https://www.unibet.fr{href}" if href.startswith("/") else href
                        urls.add(full_url)
                return urls
        except Exception:
            pass
        return set()

    with ThreadPoolExecutor(max_workers=15) as ex:
        for f in as_completed([ex.submit(fetch_country, c) for c in COUNTRIES]):
            all_match_urls.update(f.result())

    # Page principale football
    try:
        r_main = requests.get("https://www.unibet.fr/paris-football", headers=H, timeout=10)
        soup_m = BeautifulSoup(r_main.text, "html.parser")
        for a in soup_m.find_all("a", href=True):
            href = a['href']
            if "/paris-football/" in href and "vs" in href and len(href.split("/")) >= 5:
                all_match_urls.add(f"https://www.unibet.fr{href}" if href.startswith("/") else href)
    except Exception:
        pass

    unique_games = {}
    for url in all_match_urls:
        parts = url.strip("/").split("/")
        if len(parts) >= 5 and "vs" in parts[-1]:
            teams_slug = parts[-1].split("-vs-")
            if len(teams_slug) == 2:
                dom_name = teams_slug[0].replace("-", " ").title()
                ext_name = teams_slug[1].replace("-", " ").title()
                country = parts[4].replace("-", " ").title() if len(parts) >= 6 else ""
                league = parts[5].replace("-", " ").title() if len(parts) >= 6 else parts[3].replace("-", " ").title()
                league_name = f"{country} • {league}" if country else league

                key = (_clean_team_key(dom_name), _clean_team_key(ext_name))
                g_item = {
                    "id": parts[-2],
                    "dom": dom_name,
                    "ext": ext_name,
                    "league": league_name,
                    "url": url,
                    "timestamp": int(time.time()),
                    "start_time": "À venir"
                }

                if key not in unique_games:
                    unique_games[key] = g_item
                else:
                    # Remplacer les cotes boostées par la ligue officielle standard si présente
                    if "cotes-boostees" in unique_games[key]["url"].lower() and "cotes-boostees" not in url.lower():
                        unique_games[key] = g_item

    games = list(unique_games.values())
    print(f"Fixtures trouvées (uniques) : {len(games)}")
    return games


def scan_unibet_match_details(game):
    if game.get("not_found"):
        return game
    try:
        r = requests.get(game["url"], headers=H, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        json_scripts = soup.find_all("script", type="application/json")
        if not json_scripts:
            return None

        c1, cx, c2 = None, None, None
        p2_c1, p2_cx, p2_c2 = None, None, None
        over15, over25, under25 = None, None, None
        home_over05, away_over05 = None, None
        s22 = None
        btts_oui, btts_non = None, None
        start_iso = ""

        for js in json_scripts:
            content = js.string or ""
            if "EventsDetail" not in content:
                continue
            data = json.loads(content)
            events = data.get("EventsDetail", {}).get("events", [])
            if not events:
                continue
            event = events[0]

            dom = event.get("opponentA", {}).get("label") or game["dom"]
            ext = event.get("opponentB", {}).get("label") or game["ext"]
            start_iso = event.get("parsedStart") or ""

            for g in event.get("groupedMarkets", []):
                g_desc = (g.get("name") or g.get("description") or "").lower()
                for m in g.get("markets", []):
                    m_desc = (m.get("description") or "").lower()

                    # Ignorer mi-temps
                    if any(x in m_desc for x in ["mi-temps", "1ère", "2ème", "quart", "période"]) or \
                       any(x in g_desc for x in ["mi-temps", "1ère", "2ème", "quart", "période"]):
                        continue

                    outcomes = m.get("outcomes", [])

                    # 1N2
                    if m_desc in ["1 n 2", "1n2", "résultat du match"] and c1 is None:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if dom.lower() in o_desc or "1" in o_desc: c1 = p_val
                            elif ext.lower() in o_desc or "2" in o_desc: c2 = p_val
                            elif "nul" in o_desc: cx = p_val

                    # Marché spécifique Unibet "+2 gagnant (l’équipe mène par 2 buts d’avance ou gagne)"
                    if any(kw in m_desc for kw in ["+2 gagnant", "mène par 2 buts", "mène de 2 buts", "mene par 2 buts", "mene de 2 buts"]) and p2_c1 is None:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if dom.lower() in o_desc or "1" in o_desc: p2_c1 = p_val
                            elif ext.lower() in o_desc or "2" in o_desc: p2_c2 = p_val
                            elif any(k in o_desc for k in ["nul", "egalite", "égalité", ".."]): p2_cx = p_val

                    # Over 1.5
                    if (("plus / moins 1.5" in m_desc or "plus / moins 1,5" in m_desc) and over15 is None):
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over15 = p_val

                    # Over 0.5 buts équipe domicile / extérieure (ex: Plus / Moins But(s) - Marseille 0,5)
                    # Présent dans le groupe 'Plus / Moins Buts Equipe - 90 Mins'
                    if ("0,5" in m_desc or "0.5" in m_desc) and ("but" in m_desc or "buts equipe" in g_desc or "buts équipe" in g_desc):
                        is_home = (dom.lower() in m_desc or "domicile" in m_desc)
                        is_away = (ext.lower() in m_desc or "extérieur" in m_desc or "visiteur" in m_desc)
                        if not is_home and not is_away:
                            dom_w = [w for w in re.findall(r'\w+', dom.lower()) if len(w) >= 4]
                            ext_w = [w for w in re.findall(r'\w+', ext.lower()) if len(w) >= 4]
                            if dom_w and any(w in m_desc for w in dom_w): is_home = True
                            elif ext_w and any(w in m_desc for w in ext_w): is_away = True

                        if is_home and home_over05 is None:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc and p_val > 1.0:
                                    home_over05 = p_val
                        elif is_away and away_over05 is None:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc and p_val > 1.0:
                                    away_over05 = p_val

                    # Over 2.5
                    if ("plus / moins 2.5" in m_desc or "plus / moins 2,5" in m_desc) and over25 is None:
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over25 = p_val
                                elif "moins" in o_desc: under25 = p_val

                    # Score exact 2-2
                    if "score exact" in m_desc:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if o_desc in ["2 - 2", "2-2"]: s22 = p_val

                    # BTTS Oui/Non
                    if any(kw in m_desc for kw in ["les 2 équipes marqueront", "deux équipes marqueront"]) and (btts_oui is None or btts_non is None):
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip().lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if o_desc == "oui": btts_oui = p_val
                            elif o_desc == "non": btts_non = p_val
                    elif btts_oui is None and m_desc in ["quelle équipe marquera ?", "quelle équipe marquera"]:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip().lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if "les 2 équipes marquent" in o_desc or "les deux équipes marquent" in o_desc:
                                btts_oui = p_val

            # Buteur le plus proche de la moyenne des cotes
            buteur_name = None
            buteur_cote = None
            buteur_avg = None

            buteur_prices = []
            NON_PLAYER_KEYWORDS = ["oui", "non", "condition", "egalité", "égalité", "score", "match", "equipe", "équipe", "nul", "gagne", " 1-0", " 2-0", " 3-0", " 4-0", " 0-1", " 0-2", " 0-3"]

            for g in event.get("groupedMarkets", []):
                for m in g.get("markets", []):
                    m_desc_raw = (m.get("description") or "").strip().lower()
                    if any(kw in m_desc_raw for kw in ["buteur", "buteurs", "joueur marqueur", "marqueur"]) and \
                       not any(ex in m_desc_raw for ex in ["double", "triple", "combin", "2+", "duel", "trio", "quatuor"]):
                        for o in m.get("outcomes", []):
                            p_name = (o.get("description") or o.get("label") or o.get("name") or "").strip()
                            p_val_str = str(o.get("price") or o.get("currentPrice") or o.get("odds") or 0).replace(",", ".")
                            try:
                                p_val = float(p_val_str)
                            except ValueError:
                                p_val = 0.0
                            if p_val > 1.0 and p_name:
                                if not any(nk in p_name.lower() for nk in NON_PLAYER_KEYWORDS):
                                    buteur_prices.append((p_name, p_val))
                        if buteur_prices:
                            break
                if buteur_prices:
                    break

            if buteur_prices:
                pool = [(n, p) for n, p in buteur_prices if p <= 6.0] or buteur_prices
                avg_p = sum(p for n, p in pool) / len(pool)
                closest = min(pool, key=lambda x: abs(x[1] - avg_p))
                raw_name = closest[0]
                if "," in raw_name:
                    parts = raw_name.split(",", 1)
                    raw_name = f"{parts[1].strip()} {parts[0].strip()}"
                buteur_name = raw_name
                buteur_cote = closest[1]
                buteur_avg = round(avg_p, 2)

            margin_o25 = ((1.0/over25) + (1.0/under25)) if (over25 and under25 and over25 > 0 and under25 > 0) else 1.12
            over25_fair = round(over25 * margin_o25, 2) if over25 else None


            return {
                **game,
                "dom": dom,
                "ext": ext,
                "start_iso": start_iso,
                "date_str": format_french_date(start_iso),
                "c1": c1, "cx": cx, "c2": c2,
                "p2_c1": p2_c1, "p2_cx": p2_cx, "p2_c2": p2_c2,
                "home_over05": home_over05,
                "away_over05": away_over05,
                "over15": over15 or (round(1.0 + (over25 - 1.0) * 0.45, 2) if over25 else 1.25),
                "over25": over25, "under25": under25, "over25_fair": over25_fair,
                "s22": s22,
                "btts_oui": btts_oui,
                "btts_non": btts_non,
                "buteur_name": buteur_name,
                "buteur_cote": buteur_cote,
                "buteur_avg": buteur_avg,
            }
    except Exception as e:
        print(f"❌ ERROR scanning {game.get('url')}: {e}")
        return None
def sync_and_update_docs_data(retained_favs, rejected_favs, all_scanned=None):
    """
    ponytail: Source Unique de Vérité (docs/data.json).
    Synchronise les scores réels via LiveScore, met à jour les statuts (+2 buts / victoires),
    préserve l'intégrité des combinés existants (Méthode 1 & Méthode 2) et ajoute chronologiquement les nouveaux favoris.
    Garantit 100% de parité stricte entre l'e-mail envoyé et le site GitHub Pages.
    """
    from difflib import SequenceMatcher
    docs_data_path = os.path.join("docs", "data.json")
    existing_docs = {
        "summary": {},
        "matches_today": [],
        "history": [],
        "combos_summary": {},
        "combos_today": [],
        "matches_discarded": []
    }
    if os.path.exists(docs_data_path):
        try:
            with open(docs_data_path, "r", encoding="utf-8") as f_in:
                existing_docs = json.load(f_in)
        except Exception as e_load:
            print(f"⚠️ Erreur chargement docs/data.json: {e_load}")

    # 1. Fetch LiveScore for yesterday and today to update scores and statuses
    ls_events = []
    now_ls = datetime.now()
    dates_to_check = [
        (now_ls - timedelta(days=2)).strftime("%Y%m%d"),
        (now_ls - timedelta(days=1)).strftime("%Y%m%d"),
        now_ls.strftime("%Y%m%d")
    ]
    for d_str in dates_to_check:
        try:
            ls_url = f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{d_str}/0"
            r_ls = requests.get(ls_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if r_ls.status_code == 200:
                for st in r_ls.json().get("Stages", []):
                    st_name = (st.get("Cnm", "") + " • " + st.get("Snm", "")).strip()
                    for m_ev in st.get("Events", []):
                        eps = str(m_ev.get("Eps", ""))
                        tr1 = m_ev.get("Tr1")
                        tr2 = m_ev.get("Tr2")
                        h_sc = int(tr1) if tr1 is not None and str(tr1).isdigit() else None
                        a_sc = int(tr2) if tr2 is not None and str(tr2).isdigit() else None
                        ls_events.append({
                            "home": m_ev.get("T1", [{}])[0].get("Nm", ""),
                            "away": m_ev.get("T2", [{}])[0].get("Nm", ""),
                            "league": st_name,
                            "eps": eps,
                            "h_sc": h_sc,
                            "a_sc": a_sc
                        })
        except Exception as e_ls:
            print(f"⚠️ Sync LiveScore ({d_str}): {e_ls}")

    TEAM_ALIASES = {
        "potriglias": ["iraklis", "triglias", "potrigliasiraklis"],
        "iraklis": ["potriglias", "triglias"],
        "unicraiova": ["craiova", "csuniversitateacraiova", "ucraiova"],
        "universitcluj": ["universitateacluj", "ucluj"],
        "fcnarva": ["narvatrans", "transnarva", "narva"],
        "palerme": ["palermo"],
        "dlimache": ["deporteslimache", "limache"],
        "vitoriaba": ["vitoria"],
        "mantafc": ["manta"],
        "nommeunite": ["nommeunited"],
        "aekathenes": ["aekathens", "aek"],
        "intermilan": ["inter"],
        "celikzenica": ["celik", "nkcelik"],
        "stpatricks": ["stpatricksathletic", "stpats"],
        "drogheda": ["droghedaunited"],
        "fcseville": ["sevilla", "seville"],
        "seville": ["sevilla"],
        "cfvalence": ["valencia", "valence"],
        "valence": ["valencia"],
        "shelbournefc": ["shelbourne"],
        "barrytownfc": ["barrytown"],
        "defensayjus": ["defensayjusticia", "defensa"],
        "jaguares": ["cdjaguares", "jaguaresdecordoba"]
    }
    STOPWORDS = {'fc', 'cf', 'sc', 'cd', 'cs', 'de', 'la', 'le', 'el', 'club', 'deportes', 'real', 'city', 'united', 'athletic', 'sporting', 'athletique'}

    def clean_n(x): return _clean_team_key(x)
    def sim_score(a, b):
        ca, cb = clean_n(a), clean_n(b)
        if not ca or not cb: return 0.0
        if ca == cb: return 1.0
        if ca in cb or cb in ca: return 0.90
        for k, alias_list in TEAM_ALIASES.items():
            if k in ca or ca in k:
                for al in alias_list:
                    if al in cb or cb in al: return 0.92
            if k in cb or cb in k:
                for al in alias_list:
                    if al in ca or ca in al: return 0.92
        words_a = [w for w in re.split(r'[^a-z0-9]+', str(a).lower()) if len(w) >= 4 and w not in STOPWORDS]
        words_b = [w for w in re.split(r'[^a-z0-9]+', str(b).lower()) if len(w) >= 4 and w not in STOPWORDS]
        if set(words_a).intersection(set(words_b)):
            return 0.85
        return SequenceMatcher(None, ca, cb).ratio()

    # Index existing matches by unique team key
    existing_matches_map = {
        (_clean_team_key(m.get("home", "")), _clean_team_key(m.get("away", ""))): m
        for m in existing_docs.get("matches_today", [])
    }
    for c in existing_docs.get("methode2_combos", []):
        for leg in [c.get("m1", {}), c.get("m2", {})]:
            if leg.get("home") and leg.get("away"):
                k = (_clean_team_key(leg.get("home", "")), _clean_team_key(leg.get("away", "")))
                if k not in existing_matches_map:
                    existing_matches_map[k] = leg
    for c in existing_docs.get("combos_today", []):
        for leg in [c.get("m1", {}), c.get("m2", {})]:
            if leg.get("home") and leg.get("away"):
                k = (_clean_team_key(leg.get("home", "")), _clean_team_key(leg.get("away", "")))
                if k not in existing_matches_map:
                    existing_matches_map[k] = leg

    # ponytail: Actualiser en direct les cotes de matches_today avec le scan Unibet frais
    if all_scanned:
        for sm in all_scanned:
            k = (_clean_team_key(sm.get("dom", "")), _clean_team_key(sm.get("ext", "")))
            if k in existing_matches_map:
                item = existing_matches_map[k]
                c1 = sm.get("c1")
                c2 = sm.get("c2")
                if c1 and c2:
                    try:
                        c1_f = float(c1)
                        c2_f = float(c2)
                        is_dom = c1_f < c2_f
                        fresh_odds = float(sm.get("p2_c1") or c1_f) if is_dom else float(sm.get("p2_c2") or c2_f)
                        item["odds"] = fresh_odds
                        item["fav_side"] = "dom" if is_dom else "ext"
                    except Exception:
                        pass

    DAYS_FR = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
    today_day = DAYS_FR[now_ls.weekday()]
    yesterday_day = DAYS_FR[(now_ls.weekday() - 1) % 7]
    eligible_days = [yesterday_day, today_day]

    # Add or update retained_favs in matches_today
    for m in retained_favs:
        fi = m.get("fav_info", {})
        dom = m.get("dom", "")
        ext = m.get("ext", "")
        fav_team = fi.get("fav_team", dom)
        key = (_clean_team_key(dom), _clean_team_key(ext))
        existing_item = existing_matches_map.get(key)

        odds_val = fi.get("p2_fav_odds") or fi.get("fav_odds") or 1.50
        sc_val = fi.get("fav_score", 0)
        badge_tier = fi.get("fav_badge", "🥉 BRONZE")

        if existing_item:
            item = existing_item
            item["odds"] = odds_val
            item["domination_score"] = sc_val
            item["badge_tier"] = badge_tier
            item["market"] = fi.get("market", "FAV_1N2")
            item["market_label"] = fi.get("market_label", "👑 Favori (+2b)")
            item["fav_team"] = fav_team
        else:
            item = {
                "id": str(m.get("id", f"m_{len(existing_matches_map)+1}")),
                "time": m.get("date_str", "À venir"),
                "league": m.get("league", "Football"),
                "home": dom,
                "away": ext,
                "fav_team": fav_team,
                "fav_side": fi.get("fav_side", "dom"),
                "market": fi.get("market", "FAV_1N2"),
                "market_label": fi.get("market_label", "👑 Favori (+2b)"),
                "odds": odds_val,
                "domination_score": sc_val,
                "badge_tier": badge_tier,
                "win_pct_historical": fi.get("pct_fav_success", 0),
                "status": "UPCOMING",
                "selection_status": "PENDING",
                "score_display": "VS",
                "home_score": None,
                "away_score": None,
                "minute": m.get("date_str", "À venir"),
                "is_live": False,
                "is_finished": False,
                "profit": 0.0
            }
            existing_matches_map[key] = item

    # Update matches with LiveScore
    for item in existing_matches_map.values():
        dom = item.get("home", "")
        ext = item.get("away", "")
        fav_team = item.get("fav_team", dom)
        odds_val = item.get("odds", 1.50)

        # Si le match est déjà terminé et validé, pas besoin de le re-scanner
        if item.get("is_finished") and item.get("status") == "FINISHED":
            continue

        best_ev = None
        best_sim = 0.0
        for ev in ls_events:
            s1 = sim_score(dom, ev["home"])
            s2 = sim_score(ext, ev["away"])
            if s1 >= 0.65 and s2 >= 0.65:
                score = (s1 + s2) / 2.0
                if score > best_sim:
                    best_sim = score
                    best_ev = ev

        if best_ev and best_sim >= 0.75 and best_ev["h_sc"] is not None and best_ev["a_sc"] is not None:
            h_sc = best_ev["h_sc"]
            a_sc = best_ev["a_sc"]
            eps = best_ev["eps"]
            item["home_score"] = h_sc
            item["away_score"] = a_sc
            item["score_display"] = f"{h_sc} - {a_sc}"

            is_fav_home = (fav_team == dom)
            market = item.get("market", "FAV_1N2")

            if eps in ["FT", "AET", "AP"]:
                item["status"] = "FINISHED"
                item["is_finished"] = True
                item["is_live"] = False
                item["minute"] = "Terminé"
                if market == "OVER_15":
                    is_won = (h_sc + a_sc >= 2)
                    item["selection_status"] = "WON_FINAL" if is_won else "LOST"
                    item["profit"] = round(odds_val - 1.0, 2) if is_won else -1.0
                elif market == "BTTS":
                    is_won = (h_sc >= 1 and a_sc >= 1)
                    item["selection_status"] = "WON_FINAL" if is_won else "LOST"
                    item["profit"] = round(odds_val - 1.0, 2) if is_won else -1.0
                else:
                    fav_goals = h_sc if is_fav_home else a_sc
                    dog_goals = a_sc if is_fav_home else h_sc
                    lead2 = (fav_goals - dog_goals >= 2)
                    win = (fav_goals > dog_goals)
                    was_lead2 = (item.get("selection_status") == "WON_LEAD2")
                    if lead2 or was_lead2:
                        item["selection_status"] = "WON_LEAD2"
                        item["profit"] = round(odds_val - 1.0, 2)
                    elif win:
                        item["selection_status"] = "WON_FINAL"
                        item["profit"] = round(odds_val - 1.0, 2)
                    else:
                        item["selection_status"] = "LOST"
                        item["profit"] = -1.0
            elif eps not in ["NS", "CANC", "POST", "DEFD", "INT"]:
                item["status"] = "LIVE"
                item["is_live"] = True
                item["is_finished"] = False
                item["minute"] = "Mi-temps" if eps == "HT" else (eps + ("'" if eps.isdigit() else ""))

                if market == "OVER_15":
                    if h_sc + a_sc >= 2:
                        item["selection_status"] = "WON_FINAL"
                        item["profit"] = round(odds_val - 1.0, 2)
                    else:
                        item["selection_status"] = "IN_PROGRESS"
                        item["profit"] = 0.0
                elif market == "BTTS":
                    if h_sc >= 1 and a_sc >= 1:
                        item["selection_status"] = "WON_FINAL"
                        item["profit"] = round(odds_val - 1.0, 2)
                    else:
                        item["selection_status"] = "IN_PROGRESS"
                        item["profit"] = 0.0
                else:
                    fav_goals = h_sc if is_fav_home else a_sc
                    dog_goals = a_sc if is_fav_home else h_sc
                    lead2 = (fav_goals - dog_goals >= 2)
                    was_lead2 = (item.get("selection_status") == "WON_LEAD2")
                    if lead2 or was_lead2:
                        item["selection_status"] = "WON_LEAD2"
                        item["profit"] = round(odds_val - 1.0, 2)
                    else:
                        item["selection_status"] = "IN_PROGRESS"
                        item["profit"] = 0.0

    all_today_matches = list(existing_matches_map.values())
    won_c = sum(1 for x in all_today_matches if x.get("selection_status", "").startswith("WON"))
    lost_c = sum(1 for x in all_today_matches if x.get("selection_status") == "LOST")
    live_c = sum(1 for x in all_today_matches if x.get("status") == "LIVE")
    upc_c = sum(1 for x in all_today_matches if x.get("status") == "UPCOMING")
    profit_u = sum(x.get("profit", 0.0) for x in all_today_matches)
    decided_c = won_c + lost_c
    wr = round((won_c / decided_c * 100), 1) if decided_c > 0 else 0.0
    roi = round((profit_u / decided_c * 100), 2) if decided_c > 0 else 0.0

    existing_docs["summary"] = {
        "total_matches": len(all_today_matches),
        "decided_matches": decided_c,
        "won": won_c,
        "lost": lost_c,
        "live": live_c,
        "upcoming": upc_c,
        "win_rate": wr,
        "profit_units": round(profit_u, 2),
        "roi_pct": roi,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    existing_docs["matches_today"] = all_today_matches

    # 2. Update existing combos in combos_today
    existing_combos = existing_docs.get("combos_today", [])
    combo_stake = 3.0
    match_by_key = {
        (_clean_team_key(m.get("home", "")), _clean_team_key(m.get("away", ""))): m
        for m in all_today_matches
    }

    used_teams = set()
    combos_today = []
    for c in existing_combos:
        # ponytail: Règle d'or — Un ticket déjà DÉCIDÉ (WON ou LOST) est figé à jamais dans l'historique !
        if c.get("ticket_status") in ["WON", "LOST"]:
            combos_today.append(c)
            continue

        m1 = c.get("m1", {})
        m2 = c.get("m2", {})
        k1 = (_clean_team_key(m1.get("home", "")), _clean_team_key(m1.get("away", "")))
        k2 = (_clean_team_key(m2.get("home", "")), _clean_team_key(m2.get("away", "")))

        if k1 in match_by_key:
            src = match_by_key[k1]
            m1["score_display"] = src.get("score_display", m1.get("score_display"))
            m1["minute"] = src.get("minute", m1.get("minute"))
            m1["status"] = src.get("status", m1.get("status"))
            m1["selection_status"] = src.get("selection_status", m1.get("selection_status"))
        if k2 in match_by_key:
            src = match_by_key[k2]
            m2["score_display"] = src.get("score_display", m2.get("score_display"))
            m2["minute"] = src.get("minute", m2.get("minute"))
            m2["status"] = src.get("status", m2.get("status"))
            m2["selection_status"] = src.get("selection_status", m2.get("selection_status"))

        s1 = m1.get("selection_status", "PENDING")
        s2 = m2.get("selection_status", "PENDING")
        w1 = s1.startswith("WON")
        w2 = s2.startswith("WON")
        l1 = (s1 == "LOST")
        l2 = (s2 == "LOST")
        st1 = m1.get("status")
        st2 = m2.get("status")
        comb_odds = c.get("odds", 2.0)

        # Purge des combinés non conformes créés avant les nouvelles règles
        # Si un combiné n'a pas débuté (ni live, ni won/lost) et :
        # - ne respecte pas le plancher Sweet Spot (< 2.00)
        # - ou ne relève pas de la méthode 100% Favoris 1N2 (+2 Buts) (ex: anciens BTTS ou Over 1.5)
        # - ou comprend une cote inférieure au plancher (< 1.30)
        # - ou chevauche deux journées sportives différentes (Option 1 : combinés strictement Jour par Jour)
        # On le purge pour libérer les matchs vers un appairage optimal 100% même jour et 100% Favoris +2 Buts.
        is_started = (st1 == "LIVE" or st2 == "LIVE" or s1 != "PENDING" or s2 != "PENDING")
        is_corrupted = (m1.get("fav_team") not in [m1.get("home"), m1.get("away")]) or (m2.get("fav_team") not in [m2.get("home"), m2.get("away")])
        is_subpar = (comb_odds < 2.00) or (m1.get("market", "FAV_1N2") != "FAV_1N2") or (m2.get("market", "FAV_1N2") != "FAV_1N2") or (m1.get("odds", 2.0) < MIN_COTE_FAV) or (m2.get("odds", 2.0) < MIN_COTE_FAV) or is_corrupted
        d1 = _get_session_day(m1)
        d2 = _get_session_day(m2)
        is_cross_day = bool(d1 and d2 and d1 != d2)
        is_night = is_night_match(m1) or is_night_match(m2)
        if not is_started and (is_subpar or is_cross_day or is_night):
            continue

        if k1: used_teams.add(k1)
        if k2: used_teams.add(k2)
        if m1.get("away"): used_teams.add(_clean_team_key(m1.get("away")))
        if m2.get("away"): used_teams.add(_clean_team_key(m2.get("away")))

        if w1 and w2:
            c["ticket_status"] = "WON"
            c["profit_unit"] = round(comb_odds - 1.0, 2)
            c["profit_eur"] = round(c["profit_unit"] * combo_stake, 2)
        elif l1 or l2:
            c["ticket_status"] = "LOST"
            c["profit_unit"] = -1.0
            c["profit_eur"] = -combo_stake
        elif st1 == "LIVE" or st2 == "LIVE" or s1 == "IN_PROGRESS" or s2 == "IN_PROGRESS":
            c["ticket_status"] = "LIVE"
            c["profit_unit"] = 0.0
            c["profit_eur"] = 0.0
        else:
            c["ticket_status"] = "PENDING"
            c["profit_unit"] = 0.0
            c["profit_eur"] = 0.0

        combos_today.append(c)

    # 3. Pair any newly found matches from retained_favs that are not yet in combos
    unassigned_favs = []
    for m in retained_favs:
        if is_night_match(m):
            continue
        k_dom = _clean_team_key(m.get("dom", ""))
        k_ext = _clean_team_key(m.get("ext", ""))
        if k_dom not in used_teams and k_ext not in used_teams:
            unassigned_favs.append(m)

    # ponytail: Appairage intelligent Sweet Spot [2.00 - 2.85] strictly Jour par Jour (Option 1)
    pool = list(unassigned_favs)
    while len(pool) >= 2:
        best_pair = None
        best_score = 999.0
        for i in range(len(pool)):
            fi1 = pool[i].get("fav_info", {})
            c1 = fi1.get("p2_fav_odds") or fi1.get("fav_odds") or 1.50
            for j in range(i + 1, len(pool)):
                # ponytail: Option 1 — combinés strictement Jour par Jour (même session 06h-06h)
                d1 = _get_session_day(pool[i])
                d2 = _get_session_day(pool[j])
                if d1 and d2 and d1 != d2:
                    continue
                fi2 = pool[j].get("fav_info", {})
                c2 = fi2.get("p2_fav_odds") or fi2.get("fav_odds") or 1.50
                comb_odds = round(c1 * c2, 2)
                if comb_odds < 2.00 or comb_odds > 2.85:
                    continue
                dist = abs(comb_odds - 2.25)
                score = dist + (i * 0.02) + (j * 0.03)
                if score < best_score:
                    best_score = score
                    best_pair = (i, j)

        if not best_pair:
            break

        i, j = best_pair
        m2_raw = pool.pop(j)
        m1_raw = pool.pop(i)
        k1 = _clean_team_key(m1_raw.get("dom", ""))
        k2 = _clean_team_key(m2_raw.get("dom", ""))
        used_teams.add(k1)
        used_teams.add(k2)
        if m1_raw.get("ext"): used_teams.add(_clean_team_key(m1_raw.get("ext")))
        if m2_raw.get("ext"): used_teams.add(_clean_team_key(m2_raw.get("ext")))

        max_t_num = max([c.get("ticket_num", 0) for c in combos_today] or [0])
        c_idx = max_t_num + 1
        fi1 = m1_raw.get("fav_info", {})
        c1 = fi1.get("p2_fav_odds") or fi1.get("fav_odds") or 1.50
        fi2 = m2_raw.get("fav_info", {})
        c2 = fi2.get("p2_fav_odds") or fi2.get("fav_odds") or 1.50
        comb_odds = round(c1 * c2, 2)

        m1_clean = {
            "id": str(m1_raw.get("id", f"m_{k1}")),
            "time": m1_raw.get("date_str", "À venir"),
            "start_iso": m1_raw.get("start_iso"),
            "league": m1_raw.get("league", "Football"),
            "home": m1_raw.get("dom", ""),
            "away": m1_raw.get("ext", ""),
            "fav_team": fi1.get("fav_team", m1_raw.get("dom", "")),
            "fav_side": fi1.get("fav_side", "dom"),
            "market": fi1.get("market", "FAV_1N2"),
            "market_label": fi1.get("market_label", "👑 Favori (+2b)"),
            "odds": c1,
            "domination_score": fi1.get("fav_score", 60),
            "badge_tier": fi1.get("fav_badge", "🥉 BRONZE"),
            "win_pct_historical": fi1.get("pct_fav_success", 50),
            "status": "UPCOMING",
            "selection_status": "PENDING",
            "score_display": "VS",
            "home_score": 0,
            "away_score": 0,
            "minute": "À venir",
            "is_live": False,
            "is_finished": False,
            "profit": 0.0
        }

        m2_clean = {
            "id": str(m2_raw.get("id", f"m_{k2}")),
            "time": m2_raw.get("date_str", "À venir"),
            "start_iso": m2_raw.get("start_iso"),
            "league": m2_raw.get("league", "Football"),
            "home": m2_raw.get("dom", ""),
            "away": m2_raw.get("ext", ""),
            "fav_team": fi2.get("fav_team", m2_raw.get("dom", "")),
            "fav_side": fi2.get("fav_side", "dom"),
            "market": fi2.get("market", "FAV_1N2"),
            "market_label": fi2.get("market_label", "👑 Favori (+2b)"),
            "odds": c2,
            "domination_score": fi2.get("fav_score", 60),
            "badge_tier": fi2.get("fav_badge", "🥉 BRONZE"),
            "win_pct_historical": fi2.get("pct_fav_success", 50),
            "status": "UPCOMING",
            "selection_status": "PENDING",
            "score_display": "VS",
            "home_score": 0,
            "away_score": 0,
            "minute": "À venir",
            "is_live": False,
            "is_finished": False,
            "profit": 0.0
        }

        combos_today.append({
            "id": f"combo_{c_idx}",
            "ticket_num": c_idx,
            "email_ticket_num": None,
            "odds": comb_odds,
            "default_stake": combo_stake,
            "ticket_status": "PENDING",
            "profit_unit": 0.0,
            "gain_eur": round(comb_odds * combo_stake, 2),
            "profit_eur": 0.0,
            "m1": m1_clean,
            "m2": m2_clean
        })

    # 4. Number active/pending combos chronologically for the email
    active_combos = [c for c in combos_today if c.get("ticket_status") in ["PENDING", "LIVE"]]
    for idx, c in enumerate(active_combos, 1):
        c["email_ticket_num"] = idx

    # 5. Combos summary
    c_won = sum(1 for c in combos_today if c["ticket_status"] == "WON")
    c_lost = sum(1 for c in combos_today if c["ticket_status"] == "LOST")
    c_live = sum(1 for c in combos_today if c["ticket_status"] == "LIVE")
    c_upc = sum(1 for c in combos_today if c["ticket_status"] == "PENDING")
    c_dec = c_won + c_lost
    c_profit_u = sum(c["profit_unit"] for c in combos_today)
    c_wr = round((c_won / c_dec * 100), 1) if c_dec > 0 else 0.0
    c_roi = round((c_profit_u / c_dec * 100), 2) if c_dec > 0 else 0.0

    existing_docs["combos_summary"] = {
        "total_combos": len(combos_today),
        "decided_combos": c_dec,
        "won": c_won,
        "lost": c_lost,
        "live": c_live,
        "upcoming": c_upc,
        "default_stake": combo_stake,
        "win_rate": c_wr,
        "profit_units": round(c_profit_u, 2),
        "profit_eur": round(c_profit_u * combo_stake, 2),
        "roi_pct": c_roi
    }
    existing_docs["combos_today"] = combos_today

    # ── 5bis. MÉTHODE 2 (TEST) : TOUS LES FAVORIS DOMICILE (COTE ≥ 1.30 — COMBO ≥ 3.25 — SCORE ≥ 33) ──
    # ponytail: Règle d'or — favoris domicile avec cote individuelle >= 1.30, score >= 33 et cote combinée >= 3.25
    MIN_M2_COMBO_ODDS = 3.25
    MIN_M2_FAV_ODDS   = 1.30  # Cote minimale du favori domicile sur chaque match individuel
    MIN_M2_FAV_SCORE  = 33    # Score de domination minimal (>= 33/100)
    m2_existing = existing_docs.get("methode2_combos", [])
    m2_combos = []
    m2_used_keys = set()

    for c in m2_existing:
        m1 = c.get("m1", {})
        m2 = c.get("m2", {})
        k1 = (_clean_team_key(m1.get("home", "")), _clean_team_key(m1.get("away", "")))
        k2 = (_clean_team_key(m2.get("home", "")), _clean_team_key(m2.get("away", "")))

        # ponytail: Règle d'or — Un ticket déjà DÉCIDÉ (WON ou LOST) est figé à jamais dans l'historique !
        if c.get("ticket_status") in ["WON", "LOST"]:
            m2_combos.append(c)
            m2_used_keys.add(k1)
            m2_used_keys.add(k2)
            continue

        if k1 in match_by_key:
            src = match_by_key[k1]
            m1["status"] = src.get("status", m1.get("status"))
            m1["score_display"] = src.get("score_display", m1.get("score_display"))
            m1["selection_status"] = src.get("selection_status", m1.get("selection_status"))
            m1["minute"] = src.get("minute", m1.get("minute"))
            m1["home_score"] = src.get("home_score", m1.get("home_score"))
            m1["away_score"] = src.get("away_score", m1.get("away_score"))
            m1["is_finished"] = src.get("is_finished", m1.get("is_finished"))
            m1["is_live"] = src.get("is_live", m1.get("is_live"))
            if src.get("odds"):
                m1["odds"] = float(src.get("odds"))
            if src.get("domination_score") is not None:
                m1["domination_score"] = src.get("domination_score")

        if k2 in match_by_key:
            src = match_by_key[k2]
            m2["status"] = src.get("status", m2.get("status"))
            m2["score_display"] = src.get("score_display", m2.get("score_display"))
            m2["selection_status"] = src.get("selection_status", m2.get("selection_status"))
            m2["minute"] = src.get("minute", m2.get("minute"))
            m2["profit"] = src.get("profit", m2.get("profit", 0.0))
            m2["home_score"] = src.get("home_score", m2.get("home_score"))
            m2["away_score"] = src.get("away_score", m2.get("away_score"))
            m2["is_finished"] = src.get("is_finished", m2.get("is_finished"))
            m2["is_live"] = src.get("is_live", m2.get("is_live"))
            if src.get("odds"):
                m2["odds"] = float(src.get("odds"))
            if src.get("domination_score") is not None:
                m2["domination_score"] = src.get("domination_score")

        c1 = float(m1.get("odds", 1.50))
        c2 = float(m2.get("odds", 1.50))
        sc1 = m1.get("domination_score")
        sc2 = m2.get("domination_score")
        comb_odds = round(c1 * c2, 2)
        is_night = is_night_match(m1) or is_night_match(m2)

        # Si match de nuit (00h01-06h00), si les cotes réelles ont baissé (< 3.25), si une cote individuelle est < 1.30, ou si score < 33, libérer les matchs pour ré-appairage
        if c.get("ticket_status") == "PENDING":
            if is_night or c1 < MIN_M2_FAV_ODDS or c2 < MIN_M2_FAV_ODDS or comb_odds < MIN_M2_COMBO_ODDS:
                continue
            if (sc1 is not None and sc1 < MIN_M2_FAV_SCORE) or (sc2 is not None and sc2 < MIN_M2_FAV_SCORE):
                continue

        c["odds"] = comb_odds
        c["gain_eur"] = round(comb_odds * combo_stake, 2)
        m2_used_keys.add(k1)
        m2_used_keys.add(k2)

        s1 = m1.get("selection_status", "PENDING")
        s2 = m2.get("selection_status", "PENDING")
        w1 = s1.startswith("WON")
        w2 = s2.startswith("WON")
        l1 = (s1 == "LOST")
        l2 = (s2 == "LOST")
        st1 = m1.get("status")
        st2 = m2.get("status")

        if w1 and w2:
            c["ticket_status"] = "WON"
            c["profit_unit"] = round(comb_odds - 1.0, 2)
            c["profit_eur"] = round(c["profit_unit"] * combo_stake, 2)
        elif l1 or l2:
            c["ticket_status"] = "LOST"
            c["profit_unit"] = -1.0
            c["profit_eur"] = -combo_stake
        elif st1 == "LIVE" or st2 == "LIVE" or s1 == "IN_PROGRESS" or s2 == "IN_PROGRESS":
            c["ticket_status"] = "LIVE"
            c["profit_unit"] = 0.0
            c["profit_eur"] = 0.0
        else:
            c["ticket_status"] = "PENDING"
            c["profit_unit"] = 0.0
            c["profit_eur"] = 0.0

        m2_combos.append(c)

    # Récupérer tous les favoris à domicile non encore combinés
    unpaired_home_favs = []
    seen_unpaired_keys = set()

    # Source 1 : all_today_matches
    for m in all_today_matches:
        if is_night_match(m):
            continue
        if m.get("fav_side") != "dom":
            continue
        if float(m.get("odds", 0)) < MIN_M2_FAV_ODDS:
            continue
        sc = m.get("domination_score")
        if sc is not None and sc < MIN_M2_FAV_SCORE:
            continue
        k = (_clean_team_key(m.get("home", "")), _clean_team_key(m.get("away", "")))
        if k not in m2_used_keys and k not in seen_unpaired_keys:
            unpaired_home_favs.append(m)
            seen_unpaired_keys.add(k)

    # Source 2 : all_scanned (pour capturer les cotes > 2.20 non présentes dans retained_favs)
    if all_scanned:
        for m in all_scanned:
            if is_night_match(m):
                continue
            c1 = m.get("c1")
            c2 = m.get("c2")
            if c1 and c2:
                try:
                    c1_f = float(c1)
                    c2_f = float(c2)
                    if c1_f >= MIN_M2_FAV_ODDS and c1_f < c2_f:
                        sc = m.get("fav_info", {}).get("fav_score")
                        if sc is not None and sc < MIN_M2_FAV_SCORE:
                            continue
                        k = (_clean_team_key(m.get("dom", "")), _clean_team_key(m.get("ext", "")))
                        if k not in m2_used_keys and k not in seen_unpaired_keys:
                            unpaired_home_favs.append({
                                "id": str(m.get("id", f"m2_{len(seen_unpaired_keys)+1}")),
                                "time": m.get("date_str", "À venir"),
                                "start_iso": m.get("start_iso"),
                                "league": m.get("league", "Football"),
                                "home": m.get("dom", ""),
                                "away": m.get("ext", ""),
                                "odds": c1_f,
                                "domination_score": sc,
                                "fav_side": "dom",
                                "status": "UPCOMING",
                                "selection_status": "PENDING",
                                "score_display": "VS",
                                "home_score": None,
                                "away_score": None,
                                "minute": m.get("date_str", ""),
                                "dt_obj": m.get("dt_obj")
                            })
                            seen_unpaired_keys.add(k)
                except Exception:
                    pass

    # Appairage chronologique par session Jour par Jour (Option 1) avec comb_odds >= 3.25
    m2_by_session = {}
    for m in unpaired_home_favs:
        s_day = _get_session_day(m)
        m2_by_session.setdefault(s_day, []).append(m)

    for s_day, pool in sorted(m2_by_session.items()):
        while len(pool) >= 2:
            m1 = pool[0]
            c1 = float(m1.get("odds", 1.50))
            best_j = None
            for j in range(1, len(pool)):
                c2 = float(pool[j].get("odds", 1.50))
                if round(c1 * c2, 2) >= MIN_M2_COMBO_ODDS:
                    best_j = j
                    break
            if best_j is not None:
                m2 = pool.pop(best_j)
                pool.pop(0)
                c2 = float(m2.get("odds", 1.50))
                comb_odds = round(c1 * c2, 2)
                max_t = max([c.get("ticket_num", 0) for c in m2_combos] or [0])
                c_num = max_t + 1

                m1_clean = {
                    "id": str(m1.get("id", f"m2_1_{c_num}")),
                    "time": m1.get("time", m1.get("date_str", "À venir")),
                    "start_iso": m1.get("start_iso"),
                    "league": m1.get("league", "Football"),
                    "home": m1.get("home", ""),
                    "away": m1.get("away", ""),
                    "odds": c1,
                    "domination_score": m1.get("domination_score"),
                    "status": m1.get("status", "UPCOMING"),
                    "selection_status": m1.get("selection_status", "PENDING"),
                    "score_display": m1.get("score_display", "VS"),
                    "home_score": m1.get("home_score", 0),
                    "away_score": m1.get("away_score", 0),
                    "minute": m1.get("minute", ""),
                    "is_live": m1.get("is_live", False),
                    "is_finished": m1.get("is_finished", False),
                    "profit": m1.get("profit", 0.0)
                }
                m2_clean = {
                    "id": str(m2.get("id", f"m2_2_{c_num}")),
                    "time": m2.get("time", m2.get("date_str", "À venir")),
                    "start_iso": m2.get("start_iso"),
                    "league": m2.get("league", "Football"),
                    "home": m2.get("home", ""),
                    "away": m2.get("away", ""),
                    "odds": c2,
                    "domination_score": m2.get("domination_score"),
                    "status": m2.get("status", "UPCOMING"),
                    "selection_status": m2.get("selection_status", "PENDING"),
                    "score_display": m2.get("score_display", "VS"),
                    "home_score": m2.get("home_score", 0),
                    "away_score": m2.get("away_score", 0),
                    "minute": m2.get("minute", ""),
                    "is_live": m2.get("is_live", False),
                    "is_finished": m2.get("is_finished", False),
                    "profit": m2.get("profit", 0.0)
                }

                s1 = m1_clean.get("selection_status", "PENDING")
                s2 = m2_clean.get("selection_status", "PENDING")
                w1 = s1.startswith("WON")
                w2 = s2.startswith("WON")
                l1 = (s1 == "LOST")
                l2 = (s2 == "LOST")
                st1 = m1_clean.get("status")
                st2 = m2_clean.get("status")

                if w1 and w2:
                    t_st = "WON"
                    p_u = round(comb_odds - 1.0, 2)
                    p_eur = round(p_u * combo_stake, 2)
                elif l1 or l2:
                    t_st = "LOST"
                    p_u = -1.0
                    p_eur = -combo_stake
                elif st1 == "LIVE" or st2 == "LIVE" or s1 == "IN_PROGRESS" or s2 == "IN_PROGRESS":
                    t_st = "LIVE"
                    p_u = 0.0
                    p_eur = 0.0
                else:
                    t_st = "PENDING"
                    p_u = 0.0
                    p_eur = 0.0

                m2_combos.append({
                    "id": f"m2_combo_{c_num}",
                    "ticket_num": c_num,
                    "session": s_day,
                    "odds": comb_odds,
                    "default_stake": combo_stake,
                    "ticket_status": t_st,
                    "profit_unit": p_u,
                    "gain_eur": round(comb_odds * combo_stake, 2),
                    "profit_eur": p_eur,
                    "m1": m1_clean,
                    "m2": m2_clean
                })
            else:
                pool.pop(0)

    # Numéroter les combos actifs M2 pour le mail
    m2_active = [c for c in m2_combos if c.get("ticket_status") in ["PENDING", "LIVE"]]
    for idx, c in enumerate(m2_active, 1):
        c["email_ticket_num"] = idx

    m2_won = sum(1 for c in m2_combos if c["ticket_status"] == "WON")
    m2_lost = sum(1 for c in m2_combos if c["ticket_status"] == "LOST")
    m2_live = sum(1 for c in m2_combos if c["ticket_status"] == "LIVE")
    m2_upc = sum(1 for c in m2_combos if c["ticket_status"] == "PENDING")
    m2_dec = m2_won + m2_lost
    m2_prof_u = sum(c.get("profit_unit", 0.0) for c in m2_combos)
    m2_wr = round((m2_won / m2_dec * 100), 1) if m2_dec > 0 else 0.0
    m2_roi = round((m2_prof_u / m2_dec * 100), 2) if m2_dec > 0 else 0.0

    existing_docs["methode2_summary"] = {
        "total_combos": len(m2_combos),
        "decided_combos": m2_dec,
        "won": m2_won,
        "lost": m2_lost,
        "live": m2_live,
        "upcoming": m2_upc,
        "default_stake": combo_stake,
        "win_rate": m2_wr,
        "profit_units": round(m2_prof_u, 2),
        "profit_eur": round(m2_prof_u * combo_stake, 2),
        "roi_pct": m2_roi
    }
    existing_docs["methode2_combos"] = m2_combos

    # 6. Discarded matches
    discarded_list = []
    for rf in rejected_favs:
        fi = rf.get("fav_info", {})
        c_val = f"@{fi['p2_fav_odds']:.2f}" if fi.get("p2_fav_odds") else f"@{fi.get('fav_odds', 1.50):.2f}"
        discarded_list.append({
            "time": rf.get("date_str", ""),
            "league": rf.get("league", ""),
            "match": f"{rf.get('dom', '')} vs {rf.get('ext', '')}",
            "fav_team": fi.get("fav_team", ""),
            "odds": c_val,
            "domination_score": f"{fi.get('fav_score', 0)}/100",
            "reussite": f"{fi.get('pct_fav_success', 0)}%",
            "status": "ÉCARTÉ"
        })
    existing_docs["matches_discarded"] = discarded_list

    os.makedirs(os.path.dirname(docs_data_path), exist_ok=True)
    with open(docs_data_path, "w", encoding="utf-8") as f_out:
        json.dump(existing_docs, f_out, ensure_ascii=False, indent=2)
    print(f"✅ GITHUB PAGES docs/data.json EXPORTÉ & SYNCHRONISÉ : {len(combos_today)} M1 combinés ({len(active_combos)} actifs), {len(m2_combos)} M2 combinés ({len(m2_active)} actifs)")

    return existing_docs, active_combos, m2_active

def main():
    print("=== AUTOMATISATION UNIBET — MÉTHODE FOOTBALL MULTI-MARCHÉS (3 JOURNÉES + NUITS) ===")
    matches_to_scan = get_unibet_active_games()

    scanned_all = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_all.append(res)

    # Dédoublonnage strict par paire d'équipes (évite les doublons Cotes Boostées vs Ligue Officielle)
    unique_scanned = {}
    for m in scanned_all:
        key = (_clean_team_key(m.get("dom")), _clean_team_key(m.get("ext")))
        if key not in unique_scanned:
            unique_scanned[key] = m
        else:
            # Privilégier la version sans 'cotes boostees'
            if "cotes boostees" in (unique_scanned[key].get("league") or "").lower() and "cotes boostees" not in (m.get("league") or "").lower():
                unique_scanned[key] = m
    scanned_all = list(unique_scanned.values())

    # Filtre Fenêtre : Journée + Nuit suivante (36 Heures max)
    now_utc = datetime.now(timezone.utc)
    limit_36h = now_utc + timedelta(hours=36)

    scanned_results = []
    for m in scanned_all:
        start_iso = m.get("start_iso")
        if start_iso:
            try:
                m_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                if (now_utc - timedelta(hours=3)) <= m_dt <= limit_36h:
                    m["dt_obj"] = m_dt
                    scanned_results.append(m)
            except Exception:
                scanned_results.append(m)
        else:
            scanned_results.append(m)

    # Fallback de sécurité : Si aucun match dans la fenêtre 36h, prendre tous les matchs à venir
    if len(scanned_results) == 0 and scanned_all:
        print("⚠️ Aucun match dans la fenêtre 36h — Utilisation des prochains matchs disponibles...")
        scanned_results = scanned_all

    scanned_results.sort(key=lambda x: x.get("dt_obj", now_utc))
    print(f"Matchs dans la fenêtre Journée + Nuit Suivante (36h) : {len(scanned_results)}")

    # ── Enrichissement AdamChoi Score 3+ Buts /100 sur TOUS LES MATCHS SCANNÉS ──
    # Étape 1 : Import du moteur (ne doit JAMAIS échouer silencieusement)
    try:
        from analyze import analyze_pure_stats_20
        print("✅ analyze_pure_stats_20 importé avec succès")
    except Exception as e_import:
        analyze_pure_stats_20 = None
        print(f"❌ ERREUR import analyze.py : {type(e_import).__name__}: {e_import}")

    # Étape 2 : Préchargement fixtures AdamChoi (optionnel — fallback auto si échoue)
    d_fx = None
    d_refs = {}
    if analyze_pure_stats_20:
        try:
            r_fx = requests.get("https://www.adamchoi.co.uk/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0", headers={"Authorization-Client": "ADAMCHOI.CO.UK", "User-Agent": "Mozilla/5.0"}, timeout=12)
            d_fx = r_fx.json() if r_fx.status_code == 200 else None
            print(f"✅ Fixtures AdamChoi chargées : {len(d_fx.get('dates', [])) if d_fx else 0} dates")
        except Exception as e_fx:
            d_fx = None  # analyse.py fera un fetch individuel par match
            print(f"⚠️ Fixtures AdamChoi non préchargées ({type(e_fx).__name__}: {e_fx}) — fallback auto-fetch par match")
        try:
            REFS_URL = "https://www.adamchoi.co.uk/scripts/data/json/scripts/getFixturesWithRefereesSimplified.php"
            REF_HEADERS = {"Authorization-Client": "ADAMCHOI.CO.UK"}
            body_str = ""
            # Tentative 1 : curl_cffi impersonate Chrome (contourne Cloudflare TLS fingerprint)
            try:
                from curl_cffi import requests as cf_requests
                r_cf = cf_requests.get(REFS_URL, impersonate="chrome120", headers=REF_HEADERS, timeout=12)
                raw = r_cf.content
                if raw[:3] == b'\xef\xbb\xbf':
                    raw = raw[3:]
                body_str = raw.decode('utf-8', errors='replace').strip()
                if r_cf.status_code == 200 and body_str and body_str[0] in '{[':
                    print(f"   Arbitres body[0:30]: {repr(body_str[:30])} (curl_cffi Chrome)")
                else:
                    print(f"   ⚠️ curl_cffi : réponse invalide ({r_cf.status_code}), fallback requests...")
                    body_str = ""
            except Exception as e_cf:
                print(f"   ⚠️ curl_cffi non disponible ({e_cf}), fallback requests...")
                body_str = ""
            # Tentative 2 (fallback) : requests classique avec retries si curl_cffi a échoué
            if not body_str:
                for _attempt, delay in enumerate([0, 3, 5, 8]):
                    if delay:
                        time.sleep(delay)
                    try:
                        r_refs = requests.get(REFS_URL, headers={**REF_HEADERS, "User-Agent": "Mozilla/5.0"}, timeout=12)
                        raw = r_refs.content
                        if raw[:3] == b'\xef\xbb\xbf':
                            raw = raw[3:]
                        body_str = raw.decode('utf-8', errors='replace').strip()
                        if r_refs.status_code == 200 and body_str and body_str[0] in '{[':
                            print(f"   Arbitres body[0:30]: {repr(body_str[:30])} (requests tentative {_attempt+1})")
                            break
                        else:
                            print(f"   ⚠️ Tentative requests {_attempt+1}/4 : HTML/vide, retry...")
                            body_str = ""
                    except Exception as e_attempt:
                        print(f"   ⚠️ Tentative requests {_attempt+1}/4 : {e_attempt}, retry...")
                        body_str = ""
            refs_raw = json.loads(body_str) if body_str and body_str[0] in '{[' else {}
            for date_block in refs_raw.get("dates", []):
                for lg in date_block.get("leagues", []):
                    for fx in lg.get("fixtures", []):
                        eids = [str(k) for k in [fx.get("externalid"), fx.get("externalId"), fx.get("id")] if k]
                        ref_name = fx.get("refereeName") or fx.get("referee_name")
                        if ref_name and ref_name != "Inconnu":
                            ref_entry = {"refereeId": fx.get("refereeId", 0), "refereeName": ref_name}
                            for e_key in eids:
                                d_refs[e_key] = ref_entry
            print(f"✅ Arbitres désignés chargés : {len(d_refs)} entrées correspondantes")
        except Exception as e_refs:
            d_refs = {}
            print(f"⚠️ Arbitres non chargés ({type(e_refs).__name__}: {e_refs})")


    def enrich_adamchoi(m):
        if analyze_pure_stats_20:
            try:
                res = analyze_pure_stats_20(m["dom"], m["ext"], d_fx, is_batch=True, match_dt=m.get("dt_obj"), unibet_league=m.get("league", ""), d_refs=d_refs, m_unibet=m)
                if res:
                    m["ac_score"] = res.get("score", 0)
                    m["ac_classe"] = res.get("classe", "")
                    m["ac_prob"] = res.get("calibrated_prob", res.get("prob", 0))
                    m["ac_xg"] = res.get("xg_total", 0.0)
                    m["ac_sot"] = res.get("sot_total", 0.0)
                    m["ac_verdict"] = res.get("verdict", "")
                    m["ac_red_flags"] = res.get("red_flags", [])
                    m["pts_ipo"] = res.get("pts_ipo", 0)
                    m["ipo_comb"] = res.get("ipo_comb", 0.0)
                    m["pts_goals"] = res.get("pts_goals", 0)
                    m["total_goals_brut"] = res.get("total_goals_brut", 0.0)
                    m["pts_freq"] = res.get("pts_freq", 0)
                    m["avg_freq_all"] = res.get("o25_avg_rate", res.get("avg_freq_all", 0.0))
                    m["pts_sot"] = res.get("pts_sot", 0)
                    m["sot_comb"] = res.get("sot_comb", 0.0)
                    m["pts_ha"] = res.get("pts_ha", 0)
                    m["avg_freq_ha"] = res.get("avg_freq_ha", 0.0)
                    m["pts_league"] = res.get("pts_league", 0)
                    m["recent_h_dom"] = res.get("recent_h_dom", [])
                    m["recent_a_ext"] = res.get("recent_a_ext", [])
                    m["freq_o15"] = res.get("freq_o15", 0.0)
                    m["freq_btts"] = res.get("freq_btts", 0.0)
                    m["score_o15"] = res.get("score_o15", 0)
                    m["score_btts"] = res.get("score_btts", 0)
                    m["score_penalty"] = res.get("score_penalty", 0)
                    m["ref_name"] = res.get("ref_name", "Inconnu")
                    m["ref_status"] = res.get("ref_status", "Arbitre non désigné — confiance réduite")
                    m["pen_per_match"] = res.get("pen_per_match", 0.0)
                    m["avg_booking"] = res.get("avg_booking", 0.0)
                    m["peno_badge"] = res.get("peno_badge", "")
                    m["peno_status"] = res.get("peno_status", "VALIDE")
                    m["p_dom_10m"] = res.get("p_dom_10m", 0)
                    m["p_ext_10m"] = res.get("p_ext_10m", 0)
                    m["p_tot_10m"] = res.get("p_tot_10m", 0)
            except Exception:
                pass
        return m

    if scanned_results and analyze_pure_stats_20:
        print(f"📊 Enrichissement AdamChoi Score /100 pour les {len(scanned_results)} matchs scannés Unibet...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            scanned_results = list(ex.map(enrich_adamchoi, scanned_results))

    # ── Évaluation 100% Stratégie Favoris « Win & 2 Buts d'Avance (Early Payout) » ──
    retained_favs = []
    rejected_favs = []
    for m in scanned_results:
        fav_res = evaluate_favorite_domination(m)
        if fav_res:
            m["fav_info"] = fav_res
            if fav_res["fav_score"] >= MIN_SCORE_FAV_RETAINED:
                retained_favs.append(m)
            else:
                rejected_favs.append(m)

    # ponytail: Tri STRICTEMENT CHRONOLOGIQUE demandé par l'utilisateur
    retained_favs.sort(key=lambda x: x.get("dt_obj", now_utc))
    all_favs_chrono = sorted(retained_favs + rejected_favs, key=lambda x: x.get("dt_obj", now_utc))

    # ponytail: garde-fous absolus sur les matchs retenus
    assert all(m["fav_info"]["fav_odds"] <= MAX_COTE_FAV for m in retained_favs), "ERREUR: Match retenu avec Cote > 2.20"
    for i in range(len(retained_favs) - 1):
        t1 = retained_favs[i].get("dt_obj", now_utc)
        t2 = retained_favs[i + 1].get("dt_obj", now_utc)
        assert t1 <= t2, f"ERREUR: Ordre non chronologique ({t1} > {t2}) pour {retained_favs[i]['dom']} vs {retained_favs[i+1]['dom']}"

    nb_platine = sum(1 for m in retained_favs if m["fav_info"]["fav_score"] >= 85)
    nb_or = sum(1 for m in retained_favs if 75 <= m["fav_info"]["fav_score"] < 85)
    nb_argent = sum(1 for m in retained_favs if 65 <= m["fav_info"]["fav_score"] < 75)
    nb_bronze = sum(1 for m in retained_favs if 55 <= m["fav_info"]["fav_score"] < 65)
    nb_risqued = len(rejected_favs)

    print(f"🏆 Matchs analysés (Cote <= 2.20) : {len(retained_favs) + len(rejected_favs)} / {len(scanned_results)}")
    print(f"⭐ Sélections Retenues (Score >= 55, tri chronologique) : {len(retained_favs)} (💎 Platine: {nb_platine}, 🥇 Or: {nb_or}, 🥈 Argent: {nb_argent}, 🥉 Bronze: {nb_bronze})")
    print(f"⚠️ Sélections Écartées (Score < 55) : {len(rejected_favs)}")

    # ── Évolutions vs run précédent ──────────────────────────────────────────
    history_file = "previous_odds.json"
    prev_state = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                prev_state = json.load(f)
        except Exception:
            pass

    curr_state = {
        "favs": {
            m["id"]: {
                "match": f"{m['dom']} - {m['ext']}",
                "league": m["league"],
                "date_str": m["date_str"],
                "fav_team": m["fav_info"]["fav_team"],
                "fav_odds": m["fav_info"]["fav_odds"],
                "p2_fav_odds": m["fav_info"].get("p2_fav_odds"),
                "fav_score": m["fav_info"]["fav_score"],
                "fav_badge": m["fav_info"]["fav_badge"],
            }
            for m in retained_favs
        }
    }

    prev_favs = prev_state.get("favs", {})
    new_favs   = [v for k, v in curr_state["favs"].items() if k not in prev_favs]
    drop_favs  = [v for k, v in prev_favs.items() if k not in curr_state["favs"]]
    var_favs   = []
    for k, v in curr_state["favs"].items():
        if k in prev_favs:
            old_o = prev_favs[k].get("fav_odds")
            if old_o and old_o != v["fav_odds"]:
                diff = round(v["fav_odds"] - old_o, 2)
                var_favs.append({**v, "old_odds": old_o, "diff": diff})

    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(curr_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')

    # ── Bloc Évolutions HTML ─────────────────────────────────────────────────
    evo_html = ""
    if new_favs or var_favs or drop_favs:
        evo_html += '<div style="background:#fefce8; border:1px solid #fde68a; border-radius:8px; padding:15px; margin-bottom:20px;">'
        evo_html += '<h3 style="color:#92400e; margin-top:0; border-bottom:1px solid #fde68a; padding-bottom:5px;">📊 ÉVOLUTIONS DEPUIS LE DERNIER RUN (~2h)</h3>'

        if new_favs:
            evo_html += '<p style="color:#15803d; font-weight:bold; margin-bottom:5px;">🆕 Nouveaux favoris retenus :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in new_favs[:6]:
                c_txt = f"@{item['p2_fav_odds']:.2f} (Marché +2)" if item.get("p2_fav_odds") else f"@{item['fav_odds']:.2f}"
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>Favori {item['fav_team']}</b> ({c_txt}) — Score : <b>{item['fav_score']}/100</b> ({item['fav_badge']})</li>"
            if len(new_favs) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(new_favs) - 6} autres nouveaux favoris</li>"
            evo_html += '</ul>'

        if var_favs:
            evo_html += '<p style="color:#1d4ed8; font-weight:bold; margin-bottom:5px;">📈 Variations de cote :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_favs[:6]:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : Favori {item['fav_team']} cote {item['old_odds']} &rarr; <b>{item['fav_odds']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            if len(var_favs) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(var_favs) - 6} autres variations</li>"
            evo_html += '</ul>'

        if drop_favs:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Favoris sortis de la sélection :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_favs[:6]:
                evo_html += f"<li><b>{item['match']}</b> (Favori {item['fav_team']} - {item['league']})</li>"
            if len(drop_favs) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(drop_favs) - 6} autres favoris expirés ou écartés</li>"
            evo_html += '</ul>'

        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation depuis le dernier run.</div>'

    # ── Section 1 : Planning chronologique des favoris à jouer ───────────────
    plan_rows_html = ""
    for m in retained_favs:
        fi = m["fav_info"]
        sc = fi.get("fav_score", 0)
        sc_bg = "#1e40af" if sc >= 85 else ("#15803d" if sc >= 75 else ("#b45309" if sc >= 65 else "#64748b"))
        fav_team = fi.get("fav_team", "")
        fav_odds = fi.get("fav_odds", 1.50)
        p2_odds = fi.get("p2_fav_odds")
        market = fi.get("market", "FAV_1N2")
        if market == "OVER_15":
            cote_lbl = f"@{fav_odds:.2f} <span style='font-size:9px; color:#16a34a;'>(+1.5b)</span>"
            fav_icon = "⚽"
            succ_lbl = "2+ Buts"
        elif market == "BTTS":
            cote_lbl = f"@{fav_odds:.2f} <span style='font-size:9px; color:#2563eb;'>(BTTS)</span>"
            fav_icon = "🤝"
            succ_lbl = "BTTS"
        else:
            cote_lbl = f"@{p2_odds:.2f} <span style='font-size:9px; color:#1d4ed8;'>(+2)</span>" if p2_odds else f"@{fav_odds:.2f}"
            fav_icon = "👑"
            succ_lbl = "Win / +2b"
        badge = fi.get("fav_badge", "")
        pct_succ = fi.get("pct_fav_success", 0)
        plan_rows_html += (
            f'<tr>'
            f'<td style="padding:9px 8px; white-space:nowrap; border-bottom:1px solid #f1f5f9;">'
            f'<span style="background:#0f172a; color:#ffffff; font-weight:800; font-size:12px; padding:4px 9px; border-radius:6px; letter-spacing:0.3px; display:inline-block; white-space:nowrap;">⏰ {m["date_str"]}</span></td>'
            f'<td style="padding:9px 8px; border-bottom:1px solid #f1f5f9;">'
            f'<b style="font-size:13px; color:#0f172a;">{m["dom"]} <span style="color:#94a3b8; font-weight:400; font-size:11px;">vs</span> {m["ext"]}</b><br>'
            f'<span style="font-size:10px; color:#94a3b8;">{m["league"]}</span></td>'
            f'<td style="padding:9px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">'
            f'<span style="background:#eff6ff; color:#1d4ed8; font-weight:800; font-size:12px; padding:4px 8px; border-radius:6px; border:1px solid #bfdbfe; white-space:nowrap;">'
            f'{fav_icon} {fav_team}</span></td>'
            f'<td style="padding:9px 6px; text-align:center; font-weight:900; font-size:14px; color:#0f172a; border-bottom:1px solid #f1f5f9;">{cote_lbl}</td>'
            f'<td style="padding:9px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">'
            f'<span style="background:{sc_bg}; color:#fff; font-weight:800; font-size:11px; padding:3px 7px; border-radius:5px; white-space:nowrap;">'
            f'{sc}/100</span></td>'
            f'<td style="padding:9px 6px; text-align:center; font-size:11px; font-weight:700; color:#15803d; border-bottom:1px solid #f1f5f9; white-space:nowrap;">'
            f'{pct_succ}% {succ_lbl}</td>'
            f'</tr>'
        )
    if not plan_rows_html:
        plan_rows_html = '<tr><td colspan="6" style="padding:20px; text-align:center; color:#94a3b8; font-style:italic;">Aucun favori retenu sur le créneau à venir.</td></tr>'

    # ── Construction des Combinés Chronologiques de 2 Matchs (Mise 3€) ──────
    # ponytail: Source Unique de Vérité (docs/data.json). 100% de parité stricte Email & GitHub Pages.
    existing_docs, active_combos, m2_active = sync_and_update_docs_data(retained_favs, rejected_favs, all_scanned=scanned_results)

    combos_html = ""
    default_combo_stake = 3.0

    # Tri chronologique par heure de coup d'envoi du 1er match
    active_combos = sorted(active_combos, key=lambda c: c.get("m1", {}).get("start_iso") or "")

    for c in active_combos:
        c_num = c.get("email_ticket_num", c.get("ticket_num", 1))
        comb_odds = c.get("odds", 2.0)
        pot_win = c.get("gain_eur", round(default_combo_stake * comb_odds, 2))
        net_profit = round(pot_win - default_combo_stake, 2)
        m1 = c["m1"]
        m2 = c["m2"]
        c1 = m1.get("odds", 1.50)
        c2 = m2.get("odds", 1.50)
        fav1 = m1.get("fav_team", m1.get("home", ""))
        fav2 = m2.get("fav_team", m2.get("home", ""))

        def _get_leg_pick_html(m):
            mkt = m.get("market", "FAV_1N2")
            c = m.get("odds", 1.50)
            fav_t = m.get("fav_team", m.get("home", ""))
            if mkt == "OVER_15":
                return f'<span style="color:#16a34a; font-weight:700;">⚽ Over 1.5 Buts</span> @{c:.2f}'
            elif mkt == "BTTS":
                return f'<span style="color:#2563eb; font-weight:700;">🤝 Les 2 Marquent</span> @{c:.2f}'
            else:
                return f'<span style="color:#1d4ed8; font-weight:700;">👑 {fav_t}</span> @{c:.2f}'

        def _get_leg_status_html(m):
            sel_st = m.get("selection_status", "PENDING")
            st = m.get("status", "UPCOMING")
            sc = m.get("score_display", "")
            if sel_st == "WON_LEAD2":
                return f'<span style="background:#dcfce7; color:#15803d; font-weight:800; font-size:10px; padding:2px 6px; border-radius:4px; border:1px solid #86efac;">👑 +2b GAGNÉ ({sc})</span>'
            elif sel_st == "WON_FINAL":
                return f'<span style="background:#dcfce7; color:#15803d; font-weight:800; font-size:10px; padding:2px 6px; border-radius:4px; border:1px solid #86efac;">✅ VICTOIRE ({sc})</span>'
            elif sel_st == "LOST":
                return f'<span style="background:#fee2e2; color:#b91c1c; font-weight:800; font-size:10px; padding:2px 6px; border-radius:4px; border:1px solid #fca5a5;">❌ PERDU ({sc})</span>'
            elif st == "LIVE":
                min_str = m.get("minute", "En cours")
                return f'<span style="background:#fef3c7; color:#b45309; font-weight:800; font-size:10px; padding:2px 6px; border-radius:4px; border:1px solid #fde68a;">🟢 EN DIRECT {min_str} ({sc})</span>'
            else:
                return f'<span style="background:#f1f5f9; color:#64748b; font-weight:700; font-size:10px; padding:2px 6px; border-radius:4px;">⏳ À venir</span>'

        s1 = m1.get("selection_status", "PENDING")
        s2 = m2.get("selection_status", "PENDING")
        w1 = s1.startswith("WON")
        w2 = s2.startswith("WON")
        st1 = m1.get("status")
        st2 = m2.get("status")

        if (w1 and not w2) or (w2 and not w1):
            live_ticket_badge = '<span style="background:#15803d; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🔥 1/2 VALIDÉ !</span>'
        elif st1 == "LIVE" or st2 == "LIVE":
            live_ticket_badge = '<span style="background:#d97706; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🟢 EN COURS</span>'
        else:
            live_ticket_badge = ''

        combos_html += f'''
        <div style="background:#ffffff; border:1px solid #cbd5e1; border-left:4px solid #2563eb; border-radius:8px; padding:10px 12px; margin-bottom:10px; box-shadow:0 1px 4px rgba(0,0,0,0.04);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="background:#0f172a; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🎟️ TICKET #{c_num}</span>
              <span style="background:#1d4ed8; color:#ffffff; font-weight:900; font-size:12px; padding:2px 8px; border-radius:5px;">Cote @{comb_odds:.2f}</span>
              {live_ticket_badge}
            </div>
            <div style="font-size:11px; font-weight:800; color:#15803d;">
              Mise : <b>3,00 €</b> &bull; Gain Potentiel : <b>{pot_win:.2f} €</b> (+{net_profit:.2f} € net)
            </div>
          </div>
          <div style="font-size:11px; color:#334155; line-height:1.5;">
            <div style="padding:3px 0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
              <span>1️⃣ <b>{m1.get('time', '')}</b> : {m1.get('home')} vs {m1.get('away')} &rarr; {_get_leg_pick_html(m1)}</span>
              {_get_leg_status_html(m1)}
            </div>
            <div style="padding:3px 0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
              <span>2️⃣ <b>{m2.get('time', '')}</b> : {m2.get('home')} vs {m2.get('away')} &rarr; {_get_leg_pick_html(m2)}</span>
              {_get_leg_status_html(m2)}
            </div>
          </div>
        </div>
        '''

    if not combos_html:
        combos_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:12px;">Pas assez de favoris retenus pour former un combiné de 2 matchs.</div>'

    # ── Construction des Combinés Méthode 2 (Test) pour l'Email ──────
    m2_combos_html = ""
    # Tri chronologique par heure de coup d'envoi du 1er match
    m2_active = sorted(m2_active, key=lambda c: c.get("m1", {}).get("start_iso") or "")
    for c in m2_active:
        c_num = c.get("email_ticket_num", c.get("ticket_num", 1))
        comb_odds = c.get("odds", 2.0)
        pot_win = c.get("gain_eur", round(default_combo_stake * comb_odds, 2))
        net_profit = round(pot_win - default_combo_stake, 2)
        m1 = c["m1"]
        m2 = c["m2"]

        s1 = m1.get("selection_status", "PENDING")
        s2 = m2.get("selection_status", "PENDING")
        w1 = s1.startswith("WON")
        w2 = s2.startswith("WON")
        st1 = m1.get("status")
        st2 = m2.get("status")

        if (w1 and not w2) or (w2 and not w1):
            live_m2_badge = '<span style="background:#15803d; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🔥 1/2 VALIDÉ !</span>'
        elif st1 == "LIVE" or st2 == "LIVE":
            live_m2_badge = '<span style="background:#d97706; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🟢 EN COURS</span>'
        else:
            live_m2_badge = ''

        m2_combos_html += f'''
        <div style="background:#ffffff; border:1px solid #cbd5e1; border-left:4px solid #8b5cf6; border-radius:8px; padding:10px 12px; margin-bottom:10px; box-shadow:0 1px 4px rgba(0,0,0,0.04);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="background:#4c1d95; color:#ffffff; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px;">🎯 TICKET M2 #{c_num}</span>
              <span style="background:#7c3aed; color:#ffffff; font-weight:900; font-size:12px; padding:2px 8px; border-radius:5px;">Cote @{comb_odds:.2f}</span>
              {live_m2_badge}
            </div>
            <div style="font-size:11px; font-weight:800; color:#15803d;">
              Mise : <b>3,00 €</b> &bull; Gain Potentiel : <b>{pot_win:.2f} €</b> (+{net_profit:.2f} € net)
            </div>
          </div>
          <div style="font-size:11px; color:#334155; line-height:1.5;">
            <div style="padding:3px 0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
              <span>1️⃣ <b>{m1.get('time', '')}</b> : {m1.get('home')} vs {m1.get('away')} &rarr; <span style="color:#7c3aed; font-weight:700;">👑 {m1.get('home')}</span> @{float(m1.get('odds', 1.5)):.2f}</span>
              {_get_leg_status_html(m1)}
            </div>
            <div style="padding:3px 0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">
              <span>2️⃣ <b>{m2.get('time', '')}</b> : {m2.get('home')} vs {m2.get('away')} &rarr; <span style="color:#7c3aed; font-weight:700;">👑 {m2.get('home')}</span> @{float(m2.get('odds', 1.5)):.2f}</span>
              {_get_leg_status_html(m2)}
            </div>
          </div>
        </div>
        '''

    if not m2_combos_html:
        m2_combos_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:12px;">Aucun combiné Méthode 2 actif pour cette session.</div>'

    # ── Section 2 : Fiches détaillées des matchs par ordre chronologique ─────
    fav_cards_html = ""
    if retained_favs:
        for m in retained_favs:
            fi = m["fav_info"]
            sc = fi.get("fav_score", 0)
            sc_bg = "#1e40af" if sc >= 85 else ("#15803d" if sc >= 75 else ("#b45309" if sc >= 65 else "#64748b"))
            badge = fi.get("fav_badge", "")
            fav_team = fi.get("fav_team", "")
            dog_team = fi.get("dog_team", "")
            fav_side_lbl = "Domicile" if fi.get("fav_side") == "dom" else "Extérieur"
            dog_side_lbl = "Extérieur" if fi.get("fav_side") == "dom" else "Domicile"
            p2_odds = fi.get("p2_fav_odds")
            fav_odds = fi.get("fav_odds", 1.50)
            market = fi.get("market", "FAV_1N2")

            if market == "OVER_15":
                pari_cote_str = f"@{fav_odds:.2f} (Over 1.5)"
                stats_box_html = f'''
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:11px; color:#334155; line-height:1.6; margin-bottom:6px;">
                    <div>
                        <b>⚽ Fréquence Over 1.5</b> : 
                        <span style="color:#15803d; font-weight:800;">{fi.get('pct_fav_success', 0)}%</span> des derniers matchs avec 2+ buts au score final.
                    </div>
                </div>'''
            elif market == "BTTS":
                pari_cote_str = f"@{fav_odds:.2f} (Les 2 Marquent)"
                stats_box_html = f'''
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:11px; color:#334155; line-height:1.6; margin-bottom:6px;">
                    <div>
                        <b>🤝 Fréquence BTTS</b> : 
                        <span style="color:#15803d; font-weight:800;">{fi.get('pct_fav_success', 0)}%</span> des derniers matchs où les deux équipes ont marqué.
                    </div>
                </div>'''
            else:
                pari_cote_str = f"@{p2_odds:.2f} (Marché +2 Gagnant)" if p2_odds else f"@{fav_odds:.2f} (1N2)"
                stats_box_html = f'''
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:11px; color:#334155; line-height:1.6; margin-bottom:6px;">
                    <div style="margin-bottom:4px;">
                        <b>👑 {fav_team} ({fav_side_lbl})</b> : 
                        <span style="color:#15803d; font-weight:800;">{fi.get('pct_fav_success', 0)}%</span> de matchs gagnés ou menés par 2+ buts 
                        <span style="color:#64748b;">({fi.get('pct_fav_win', 0)}% victoires, {fi.get('pct_fav_lead2', 0)}% avec 2+ buts d'écart, {fi.get('pct_fav_cs', 0)}% clean sheets &bull; marque {fi.get('avg_fav_gf', 0)} b/m)</span>
                    </div>
                    <div>
                        <b>🛡️ {dog_team} ({dog_side_lbl})</b> : 
                        <span style="color:#dc2626; font-weight:800;">{fi.get('pct_dog_loss', 0)}%</span> de défaites 
                        <span style="color:#64748b;">({fi.get('pct_dog_trailed2', 0)}% mené de 2+ buts, {fi.get('pct_dog_no_goal', 0)}% sans but marqué &bull; encaisse {fi.get('avg_dog_ga', 0)} b/m)</span>
                    </div>
                </div>'''

            proof = render_fav_proof_html(m)

            fav_cards_html += f'''
            <div style="background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid {sc_bg}; border-radius:10px; padding:12px 14px; margin-bottom:14px; box-shadow:0 2px 6px rgba(0,0,0,0.04);">
                <!-- En-tête : Heure très visible + Ligue + Score & Badge -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="background:#0f172a; color:#ffffff; font-weight:800; font-size:12px; padding:4px 9px; border-radius:6px; letter-spacing:0.3px;">⏰ {m['date_str']}</span>
                        <span style="color:#64748b; font-size:11px; font-weight:600;">🏆 {m['league']}</span>
                    </div>
                    <span style="background:{sc_bg}; color:#ffffff; font-weight:800; font-size:11px; padding:3px 9px; border-radius:6px;">
                        {badge} &bull; Score : {sc}/100
                    </span>
                </div>

                <!-- Match & Pari Conseillé -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:6px;">
                    <span style="font-size:15px; font-weight:800; color:#0f172a;">
                        ⚽ {m['dom']} <span style="color:#94a3b8; font-weight:400; font-size:12px;">vs</span> {m['ext']}
                    </span>
                    <span style="background:#eff6ff; color:#1d4ed8; font-weight:800; font-size:13px; padding:4px 10px; border-radius:6px; border:1px solid #bfdbfe;">
                        ⭐ Pari Conseillé : <b>{fav_team}</b> {pari_cote_str}
                    </span>
                </div>

                <!-- Statistiques Clés 100% Token 0 AdamChoi -->
                {stats_box_html}

                <!-- Pastilles des 10 derniers matchs récents Dom/Ext -->
                {proof}
            </div>'''
    else:
        fav_cards_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:12px;">Aucun favori éligible sur ce créneau.</div>'

    # ── Section 3 : Tableau chronologique de tous les favoris analysés ───────
    scan_rows_html = ""
    for m in all_favs_chrono:
        fi = m["fav_info"]
        retained = (fi["fav_score"] >= MIN_SCORE_FAV_RETAINED)
        bg_row = "#f0fdf4" if retained else "#ffffff"
        badge_cell = f'<span style="color:#15803d; font-weight:700;">✅ RETENU ({fi["fav_badge"]})</span>' if retained else '<span style="color:#94a3b8;">⚠️ ÉCARTÉ</span>'
        sc = fi["fav_score"]
        sc_bg = "#dcfce7" if sc >= 75 else ("#fef3c7" if sc >= 65 else "#fee2e2")
        sc_cl = "#15803d" if sc >= 75 else ("#92400e" if sc >= 65 else "#dc2626")
        score_badge = f'<span style="background:{sc_bg}; color:{sc_cl}; font-weight:800; font-size:11px; padding:2px 7px; border-radius:5px;">{sc}/100</span>'
        c_val = f"@{fi['p2_fav_odds']:.2f}" if fi.get("p2_fav_odds") else f"@{fi['fav_odds']:.2f}"

        scan_rows_html += (
            f'<tr style="background:{bg_row};">'
            f'<td style="padding:7px 8px; font-size:11px; color:#475569; border-bottom:1px solid #f1f5f9; white-space:nowrap;">{m.get("date_str", "")}</td>'
            f'<td style="padding:7px 8px; font-size:12px; font-weight:700; color:#0f172a; border-bottom:1px solid #f1f5f9;">{m.get("dom", "")} vs {m.get("ext", "")}'
            f'<br><span style="font-size:10px; color:#94a3b8; font-weight:400;">{m.get("league", "")}</span></td>'
            f'<td style="padding:7px 6px; text-align:center; font-weight:700; font-size:11px; border-bottom:1px solid #f1f5f9;">{fi["fav_team"]}</td>'
            f'<td style="padding:7px 6px; text-align:center; font-weight:800; font-size:12px; border-bottom:1px solid #f1f5f9;">{c_val}</td>'
            f'<td style="padding:7px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">{score_badge}</td>'
            f'<td style="padding:7px 6px; text-align:center; font-weight:700; font-size:11px; color:#15803d; border-bottom:1px solid #f1f5f9;">{fi["pct_fav_success"]}%</td>'
            f'<td style="padding:7px 6px; text-align:center; font-size:11px; border-bottom:1px solid #f1f5f9;">{badge_cell}</td>'
            f'</tr>'
        )

    # ── Email HTML Nouveau Design (100% Stratégie +2 Gagnant / Victoire) ──────
    now_local = datetime.now(timezone(timedelta(hours=2)))
    days_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    date_header = now_local.strftime(f"{days_fr[now_local.weekday()]} %d/%m/%Y · %Hh%M")
    nb_retained = len(retained_favs)
    nb_all_favs = len(all_favs_chrono)
    nb_scanned  = len(scanned_results)

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
      <body style="font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif; background:#f1f5f9; margin:0; padding:12px; color:#1e293b;">
        <div style="max-width:700px; margin:0 auto; background:#ffffff; border-radius:14px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">

          <!-- HEADER -->
          <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%); padding:22px 24px; text-align:center;">
            <div style="font-size:10px; letter-spacing:2px; text-transform:uppercase; color:#38bdf8; font-weight:800; margin-bottom:6px;">⚽ STRATÉGIE OFFICIELLE UNIBET · +2 GAGNANT</div>
            <h1 style="margin:0; font-size:21px; font-weight:900; color:#ffffff;">{date_header}</h1>
            <p style="margin:7px 0 0 0; font-size:12px; color:#cbd5e1;">Équipe mène de 2 buts à un moment OU gagne le match · Tri Chronologique Strict</p>
          </div>

          <!-- ENCART RÈGLE OFFICIELLE GAGNANTE -->
          <div style="background:#f0fdf4; border-bottom:1px solid #bbf7d0; border-top:1px solid #bbf7d0; padding:12px 16px; font-size:12px; color:#166534; line-height:1.5;">
            💡 <b>RÈGLE OFFICIELLE UNIBET (100% GAGNANT) :</b> Dès que votre favori mène par <b>2 buts d'avance</b> (2-0, 3-1, 4-2...) à <b>n'importe quel moment du match</b>, votre pari est <b>PAYÉ GAGNANT IMMÉDIATEMENT</b> ! Même en cas d'égalisation à <b>2-2</b> ou de défaite <b>2-3</b>, le gain reste 100% acquis. Si l'équipe gagne simplement 1-0 ou 2-1 sans break de 2 buts, le pari est <b>également gagnant</b>.
          </div>

          <!-- COMPTEURS -->
          <div style="background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:14px 16px;">
            <table style="width:100%; border-collapse:collapse; text-align:center;">
              <tr>
                <td style="padding:0 4px;"><div style="background:#dbeafe; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#1d4ed8;">{nb_retained}</div><div style="font-size:10px; font-weight:700; color:#1d4ed8;">FAVORIS RETENUS</div><div style="font-size:10px; color:#3b82f6;">Score Domination ≥ 55/100</div></div></td>
                <td style="padding:0 4px;"><div style="background:#fef3c7; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#b45309;">{nb_all_favs}</div><div style="font-size:10px; font-weight:700; color:#b45309;">FAVORIS ÉTUDIÉS</div><div style="font-size:10px; color:#d97706;">Cote 1N2 ≤ 2.20</div></div></td>
                <td style="padding:0 4px;"><div style="background:#f0fdf4; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#15803d;">{nb_scanned}</div><div style="font-size:10px; font-weight:700; color:#15803d;">MATCHS SCANNÉS</div><div style="font-size:10px; color:#16a34a;">Unibet France</div></div></td>
              </tr>
            </table>
          </div>

          <!-- SECTION 1 : PLANNING HEURE PAR HEURE -->
          <div style="padding:16px 16px 8px 16px;">
            <div style="font-size:14px; font-weight:900; color:#0f172a; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <span>📅 CE QUE VOUS DEVEZ JOUER — HEURE PAR HEURE</span>
              <span style="font-size:11px; background:#eff6ff; color:#1d4ed8; font-weight:700; padding:2px 8px; border-radius:6px;">{nb_retained} pari(s) chronologique(s)</span>
            </div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <thead><tr style="background:#0f172a; color:#ffffff; font-size:10px; text-transform:uppercase; font-weight:700;">
                  <th style="padding:9px 8px; text-align:left; white-space:nowrap;">Heure</th>
                  <th style="padding:9px 8px; text-align:left;">Match & Ligue</th>
                  <th style="padding:9px 6px; text-align:center;">Pari Conseillé</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Cote</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Score Dom.</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Réussite Win/+2b</th>
                </tr></thead>
                <tbody>{plan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- EVOLUTIONS -->
          <div style="padding:0 16px 8px 16px;">{evo_html}</div>

          <!-- SECTION COMBINÉS DE 2 MATCHS (CHRONOLOGIQUE · MISE 3€) -->
          <div style="padding:14px 16px 8px 16px; background:#f1f5f9; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:900; color:#0f172a; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <span>🎟️ VOS COMBINÉS DE 2 MATCHS (CHRONOLOGIQUE)</span>
              <span style="font-size:11px; background:#2563eb; color:#ffffff; font-weight:700; padding:2px 8px; border-radius:6px;">Mise : 3,00 € par ticket</span>
            </div>
            <div style="font-size:11px; color:#64748b; margin-bottom:10px;">
              Paires chronologiques consécutives selon l'ordre officiel de coup d'envoi. Dès qu'une équipe mène de 2 buts, sa sélection est payée immédiatement.
            </div>
            {combos_html}
          </div>

          <!-- SECTION COMBINÉS MÉTHODE 2 (TEST EXPÉRIMENTAL) -->
          <div style="padding:14px 16px 8px 16px; background:#faf5ff; border-top:2px solid #e9d5ff;">
            <div style="font-size:14px; font-weight:900; color:#4c1d95; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
              <span>🎯 MÉTHODE 2 (TEST) · FAVORIS DOMICILE (COTE TOTALE ≥ 3.25 & SCORE ≥ 33)</span>
              <span style="font-size:11px; background:#7c3aed; color:#ffffff; font-weight:700; padding:2px 8px; border-radius:6px;">Mise : 3,00 € &bull; {len(m2_active)} ticket(s)</span>
            </div>
            <div style="font-size:11px; color:#6b21a8; margin-bottom:10px; line-height:1.4;">
              💡 <b>Stratégie Test</b> : Équipes à domicile favorites (cote &ge; 1.30, score &ge; 33/100), combinées par session jour avec cote &ge; 3.25. Gain dès +2 buts d'avance ou victoire.
            </div>
            {m2_combos_html}
          </div>

          <!-- SECTION 2 : FICHES D'ANALYSE DÉTAILLÉES -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:900; color:#0f172a; margin-bottom:10px;">
              👑 FICHES D'ANALYSE DÉTAILLÉES DES FAVORIS RETENUS ({nb_retained})
              <div style="font-size:11px; font-weight:500; color:#64748b; margin-top:2px;">Historique 100% réel AdamChoi Token 0 &bull; Domicile vs Extérieur &bull; Pastilles de validation</div>
            </div>
            {fav_cards_html}
          </div>

          <!-- SECTION 3 : TOUS LES FAVORIS ANALYSÉS (ORDRE CHRONOLOGIQUE) -->
          <div style="padding:12px 16px 10px 16px; background:#ffffff; border-top:2px solid #e2e8f0;">
            <div style="font-size:13px; font-weight:800; color:#475569; margin-bottom:8px;">📊 TOUS LES FAVORIS ANALYSÉS ({nb_all_favs} favoris classés par heure)</div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <thead><tr style="background:#f1f5f9; color:#64748b; font-size:10px; text-transform:uppercase; font-weight:700; border-bottom:1px solid #e2e8f0;">
                  <th style="padding:7px 8px; text-align:left;">Heure</th>
                  <th style="padding:7px 8px; text-align:left;">Match & Ligue</th>
                  <th style="padding:7px 6px; text-align:center;">Favori</th>
                  <th style="padding:7px 6px; text-align:center;">Cote</th>
                  <th style="padding:7px 6px; text-align:center;">Score</th>
                  <th style="padding:7px 6px; text-align:center;">Win / +2b</th>
                  <th style="padding:7px 6px; text-align:center;">Statut</th>
                </tr></thead>
                <tbody>{scan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- FOOTER -->
          <div style="padding:12px 20px; background:#0f172a; font-size:10px; color:#94a3b8; text-align:center; line-height:1.5;">
            ⚠️ Paris sportifs · Unibet France · Analyse 100% AdamChoi Token 0 · Mène de 2 buts ou gagne · {now_str}
          </div>

        </div>
      </body>
    </html>
    """

    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ SÉLECTION OFFICIELLE UNIBET — +2 GAGNANT (MÈNE DE 2 BUTS OU GAGNE)",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {nb_scanned}  |  **Favoris analysés** : {nb_all_favs}  |  **Favoris retenus** : {nb_retained}",
        f"**Règle d'or Unibet** : Si l'équipe mène de 2 buts (2-0, 3-1, 4-2...) à n'importe quel moment du match, le pari est PAYÉ GAGNANT immédiatement (même en cas d'égalisation à 2-2 ou défaite 2-3). Si l'équipe gagne simplement 1-0 ou 2-1, le pari est également gagnant à la fin du match.\n",
        "## 📅 Planning Chronologique des Favoris Retenus",
        "| Heure | Ligue | Match | Favori Conseillé | Cote (+2 / 1N2) | Score Domination | Réussite Win / +2b |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: |",
    ]
    for m in retained_favs:
        fi = m["fav_info"]
        mkt = fi.get("market", "FAV_1N2")
        if mkt == "OVER_15":
            c_val = f"@{fi['fav_odds']:.2f} (Over 1.5)"
        elif mkt == "BTTS":
            c_val = f"@{fi['fav_odds']:.2f} (BTTS)"
        else:
            c_val = f"@{fi['p2_fav_odds']:.2f} (+2 Gagnant)" if fi.get("p2_fav_odds") else f"@{fi['fav_odds']:.2f} (1N2)"
        report.append(f"| {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{fi['fav_team']}** | **{c_val}** | **{fi['fav_score']}/100** ({fi['fav_badge']}) | **{fi['pct_fav_success']}%** |")

    report.append(f"\n## 📊 Tous les Favoris Analysés ({nb_all_favs})\n")
    report.append("| Heure | Ligue | Match | Favori | Cote | Score Domination | Réussite Win/+2b | Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
    for m in all_favs_chrono:
        fi = m["fav_info"]
        c_val = f"@{fi['p2_fav_odds']:.2f}" if fi.get("p2_fav_odds") else f"@{fi['fav_odds']:.2f}"
        stat = "✅ RETENU" if fi["fav_score"] >= MIN_SCORE_FAV_RETAINED else "⚠️ ÉCARTÉ"
    report.append(f"\n## 🎯 Méthode 2 (Test) : Favoris Domicile (Cote Combinée ≥ 3.25 & Score ≥ 33)\n")
    report.append(f"**Tickets actifs** : {len(m2_active)}  |  **Mise** : 3.00 €  |  **Règle** : +2 Buts d'Avance ou Victoire 1N2\n")
    report.append("| Ticket | Cote Totale | Match 1 (Heure & Cote) | Match 2 (Heure & Cote) | Statut |")
    report.append("| :---: | :---: | :--- | :--- | :---: |")
    for c in m2_active:
        num = c.get("email_ticket_num", c.get("ticket_num"))
        m1 = c["m1"]
        m2 = c["m2"]
        report.append(f"| #{num} | @{c['odds']:.2f} | {m1.get('home')} vs {m1.get('away')} ({m1.get('time')}) @{float(m1.get('odds', 1.5)):.2f} | {m2.get('home')} vs {m2.get('away')} ({m2.get('time')}) @{float(m2.get('odds', 1.5)):.2f} | {c['ticket_status']} |")

    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    # ── Envoi d'email Multi-Fournisseurs (SFR + Gmail SMTP) ─────────────────
    recipients     = [r.strip() for r in os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr, langlet.gregory@gmail.com").split(",") if r.strip()]
    gmail_email    = os.environ.get("GMAIL_EMAIL", "langlet.gregory@gmail.com")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    smtp_host      = os.environ.get("SMTP_HOST", "smtp.sfr.fr")
    smtp_port      = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user      = os.environ.get("SMTP_USER", "gregory.langlet@sfr.fr")
    smtp_pass      = os.environ.get("SMTP_PASS", "6#P31LcrCX9!")

    now_dt = datetime.now(ZoneInfo("Europe/Paris")) if ZoneInfo else datetime.now(timezone.utc)
    subject_date = now_dt.strftime('%d/%m à %Hh%M')
    raw_subject = f"⚽ +2 Gagnant {subject_date} — {nb_retained} Favoris Retenus (Mène de 2 Buts ou Gagne · Chronologique)"
    
    # Nettoyage ASCII du sujet pour compatibilité maximale MTA
    clean_subject = unicodedata.normalize('NFKD', raw_subject).encode('ASCII', 'ignore').decode('ASCII')
    if not clean_subject.strip():
        clean_subject = f"Rapport +2 Gagnant du {subject_date} - {nb_retained} favoris"

    msg = MIMEMultipart('alternative')
    msg["Subject"] = clean_subject
    msg["From"] = f"Gregory LANGLET <{gmail_email}>"
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg["X-Mailer"] = "Python/smtplib"

    plain_fallback = f"Rapport +2 Gagnant du {subject_date} - {nb_retained} favoris retenus. Consultez la version HTML pour les details complets."
    msg.attach(MIMEText(plain_fallback, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    sent_success = False

    # Tentative Gmail SMTP prioritaire (Standard MIME RFC 5322)
    if gmail_password:
        try:
            print(f"Sending email to {recipients} via Gmail SMTP (Standard MIME)...")
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(gmail_email, gmail_password)
                server.sendmail(gmail_email, recipients, msg.as_string())
            print("SUCCESS! Email sent via Gmail SMTP.")
            sent_success = True
        except Exception as e:
            print(f"Failed sending email via Gmail SMTP: {e}")

    # Fallback SFR SMTP si configuré
    if not sent_success and smtp_host and smtp_user and smtp_pass:
        try:
            msg_sfr = MIMEMultipart('alternative')
            msg_sfr["Subject"] = clean_subject
            msg_sfr["From"] = f"Gregory LANGLET <{smtp_user}>"
            msg_sfr["To"] = ", ".join(recipients)
            msg_sfr["Date"] = formatdate(localtime=True)
            msg_sfr["Message-ID"] = make_msgid()
            msg_sfr.attach(MIMEText(plain_fallback, 'plain', 'utf-8'))
            msg_sfr.attach(MIMEText(html_body, 'html', 'utf-8'))

            sfr_auth_user = smtp_user.split("@")[0] if "@" in smtp_user else smtp_user

            print(f"Sending email to {recipients} via {smtp_host}:{smtp_port}...")
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(sfr_auth_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg_sfr.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(sfr_auth_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg_sfr.as_string())
            print(f"SUCCESS! Email sent via {smtp_host}.")
            sent_success = True
        except Exception as e:
            print(f"Failed sending email via {smtp_host}: {e}")

    if not sent_success:
        print("WARNING: Email could not be delivered through any SMTP provider.")

    # ── Export direct vers le Dashboard Web (Alignement 100% avec l'Email) ────
    try:
        dash_matches = []
        retained_ids = {m.get("id") for m in retained_favs}

        for m in all_favs_chrono:
            fi = m.get("fav_info", {})
            is_sel = m.get("id") in retained_ids
            dash_matches.append({
                "id": str(m.get("id")),
                "dom": m.get("dom"),
                "ext": m.get("ext"),
                "league": m.get("league", "Football"),
                "start_iso": m.get("start_iso"),
                "date_str": m.get("date_str", "À venir"),
                "status": "UPCOMING",
                "score_dom": None,
                "score_ext": None,
                "is_selected": is_sel,
                "selection_status": "PENDING",
                "fav_team": fi.get("fav_team"),
                "fav_odds": fi.get("fav_odds"),
                "p2_odds": fi.get("p2_fav_odds"),
                "fav_score": fi.get("fav_score", 0),
                "fav_badge": fi.get("fav_badge", ""),
                "pct_fav_success": fi.get("pct_fav_success", 0),
                "btts_oui": m.get("btts_oui"),
                "btts_non": m.get("btts_non"),
                "over25": m.get("over25"),
                "ac_score": fi.get("fav_score", 0),
                "profit_units": 0.0
            })

        summary = {
            "total_live": 0,
            "total_scanned_upcoming": len(scanned_results),
            "total_selected_upcoming": len(retained_favs),
            "total_history_bets": 0,
            "total_wins": 0,
            "total_losses": 0,
            "win_rate_over25": 0.0,
            "total_profit_units": 0.0,
            "roi_pct": 0.0,
            "initial_bankroll": 100.0,
            "current_bankroll": 100.0,
            "last_update": datetime.now(timezone.utc).isoformat()
        }

        dash_data = {
            "summary": summary,
            "bankroll_curve": [],
            "league_stats": [],
            "tickets_2matches": [],
            "matches": dash_matches
        }

        if os.name == "nt":
            dash_path = r"C:\Users\grego\Documents\DEV_DIVERS\penalty\dashboard\public\data\matches.json"
            os.makedirs(os.path.dirname(dash_path), exist_ok=True)
            with open(dash_path, "w", encoding="utf-8") as f:
                json.dump(dash_data, f, ensure_ascii=False, indent=2)
            print(f"✅ DASHBOARD JSON EXPORTÉ AVEC SUCCÈS (Alignement 100% Email) : {dash_path}")

        # ── Export GitHub Pages (docs/data.json) ──
        # Déjà exporté et synchronisé en amont par sync_and_update_docs_data (Source Unique de Vérité)
        print("✅ GITHUB PAGES docs/data.json déjà synchronisé et aligné avec l'e-mail.")
    except Exception as e:
        print(f"⚠️ Erreur d'export Dashboard JSON : {e}")

    # ── 🗄️ Enregistrement Infrastructure Backtest (backtest_ledger.json) ──
    try:
        ledger_path = "backtest_ledger.json"
        existing = []
        if os.path.exists(ledger_path):
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        seen_ids = {entry.get("match_id") for entry in existing if isinstance(entry, dict)}
        now_iso = datetime.now(timezone.utc).isoformat()
        retained_ids = {m.get("id") for m in retained_favs}

        new_entries = 0
        for m in all_favs_chrono:
            m_id = m.get("id")
            if not m_id or m_id in seen_ids:
                continue

            fi = m.get("fav_info", {})
            is_retained = m_id in retained_ids
            mkt = fi.get("market", "FAV_1N2")
            sels = [mkt] if is_retained else []

            entry = {
                "match_id": m_id,
                "timestamp_utc": now_iso,
                "match": f"{m.get('dom')} vs {m.get('ext')}",
                "league": m.get("league"),
                "date_str": m.get("date_str"),
                "fav_team": fi.get("fav_team"),
                "fav_side": fi.get("fav_side"),
                "scores": {
                    "fav_score": fi.get("fav_score", 0),
                    "pct_fav_success": fi.get("pct_fav_success", 0),
                    "pct_fav_lead2": fi.get("pct_fav_lead2", 0)
                },
                "odds": {
                    "fav_odds": fi.get("fav_odds"),
                    "p2_fav_odds": fi.get("p2_fav_odds")
                },
                "selected_markets": sels,
                "result": None,
                "won_p2": None
            }
            existing.append(entry)
            seen_ids.add(m_id)
            new_entries += 1

        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"📊 BACKTEST LEDGER MAJ : {len(existing)} matchs enregistrés dans {ledger_path} (+{new_entries} nouveaux)")
    except Exception as e_ledger:
        print(f"⚠️ Erreur MAJ Backtest Ledger : {e_ledger}")

if __name__ == "__main__":
    main()

