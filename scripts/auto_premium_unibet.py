import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import email.policy
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Seuils ──────────────────────────────────────────────────────────────────
SEUIL_S3      = 12.00  # Score exact 2-2 Unibet <= 12.00
MIN_COTE_O25  = 1.55   # Cote Over 2.5 minimale = 1.55
MAX_COTE_O25  = 1.70   # Cote Over 2.5 maximale = 1.70

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}

COUNTRIES = [
    "france", "angleterre", "espagne", "italie", "allemagne", "portugal", "pays-bas",
    "belgique", "ecosse", "suisse", "autriche", "turquie", "grece", "pologne", "croatie",
    "serbie", "roumanie", "ukraine", "republique-tcheque", "hongrie", "bulgarie", "slovaquie",
    "suede", "norvege", "danemark", "finlande", "irlande", "islande", "lettonie", "lituanie", "estonie",
    "bresil", "argentine", "colombie", "mexique", "chili", "equateur", "paraguay", "uruguay", "usa", "canada",
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

def _clean_team_key(name):
    if not name: return ""
    n = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('ASCII').lower()
    return re.sub(r'[^a-z0-9]', '', n)

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
        over15, over25, under25 = None, None, None
        s22 = None
        btts_oui, btts_non = None, None
        mt1_odds = None
        mt2_odds = None
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
                for m in g.get("markets", []):
                    m_desc = (m.get("description") or "").lower()
                    outcomes = m.get("outcomes", [])

                    # ── Cotes "Mi-temps la plus prolifique" 1T et 2T (depuis JSON) ──
                    if "prolif" in m_desc:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip().lower()
                            p_val_s = str(o.get("price") or o.get("currentPrice") or 0).replace(",", ".")
                            try:
                                p_val = float(p_val_s)
                            except ValueError:
                                p_val = 0.0
                            if p_val > 1.0:
                                if mt2_odds is None and any(k in o_desc for k in ["2nde", "2ème", "2eme", "deuxième", "second"]):
                                    mt2_odds = p_val
                                elif mt1_odds is None and any(k in o_desc for k in ["1ère", "1ere", "première", "premier", "first"]):
                                    mt1_odds = p_val

                    # Ignorer mi-temps pour les autres marchés
                    if any(x in m_desc for x in ["mi-temps", "1ère", "2ème", "quart", "période"]):
                        continue

                    # 1N2
                    if m_desc in ["1 n 2", "1n2", "résultat du match"] and c1 is None:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if dom.lower() in o_desc or "1" in o_desc: c1 = p_val
                            elif ext.lower() in o_desc or "2" in o_desc: c2 = p_val
                            elif "nul" in o_desc: cx = p_val

                    # Over 1.5
                    if ("plus / moins 1.5" in m_desc or "plus / moins 1,5" in m_desc) and over15 is None:
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over15 = p_val

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
                "over15": over15 or (round(1.0 + (over25 - 1.0) * 0.45, 2) if over25 else 1.25),
                "over25": over25, "under25": under25, "over25_fair": over25_fair,
                "s22": s22,
                "btts_oui": btts_oui,
                "btts_non": btts_non,
                "buteur_name": buteur_name,
                "buteur_cote": buteur_cote,
                "buteur_avg": buteur_avg,
                "mt1_odds": mt1_odds,
                "mt2_odds": mt2_odds,
            }
    except Exception as e:
        print(f"❌ ERROR scanning {game.get('url')}: {e}")
        return None
    return None

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

    # Filtre Fenêtre : Matchs de journée uniquement (08h00 - 23h59, heure de Paris)
    # ZÉRO match de nuit (entre 00h00 et 07h59) — Fenêtre élargie à 84h (3,5 journées / week-end complet)
    now_utc = datetime.now(timezone.utc)
    paris_tz = timezone(timedelta(hours=2))
    limit_84h = now_utc + timedelta(hours=84)

    scanned_results = []
    for m in scanned_all:
        start_iso = m.get("start_iso")
        if start_iso:
            try:
                m_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                local_dt = m_dt.astimezone(paris_tz)
                # Exclusion stricte des matchs de nuit (00h00 à 07h59)
                if local_dt.hour < 8 or local_dt.hour >= 24:
                    continue
                if (now_utc - timedelta(hours=3)) <= m_dt <= limit_84h:
                    m["dt_obj"] = m_dt
                    scanned_results.append(m)
            except Exception:
                pass

    # Fallback de sécurité : Si aucun match dans la fenêtre, prendre matchs à venir sans la nuit
    if len(scanned_results) == 0 and scanned_all:
        print("⚠️ Aucun match dans la fenêtre — Fallback matchs journée à venir...")
        for m in scanned_all:
            start_iso = m.get("start_iso")
            if start_iso:
                try:
                    m_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                    local_dt = m_dt.astimezone(paris_tz)
                    if 8 <= local_dt.hour <= 23 and m_dt >= now_utc:
                        m["dt_obj"] = m_dt
                        scanned_results.append(m)
                except Exception:
                    pass

    scanned_results.sort(key=lambda x: x.get("dt_obj", now_utc))
    print(f"Matchs de journée retenus (08h00-23h59) : {len(scanned_results)}")

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
                        eid = str(fx.get("externalid", ""))
                        if eid and fx.get("refereeId"):
                            d_refs[eid] = {"refereeId": fx["refereeId"], "refereeName": fx.get("refereeName", "Inconnu")}
            print(f"✅ Arbitres désignés chargés : {len(d_refs)} matchs")
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
                    m["score_2t"] = res.get("score_2t", 0)
                    m["pct_2t_dom"] = res.get("pct_2t_dom", 0)
                    m["pct_2t_ext"] = res.get("pct_2t_ext", 0)
                    m["score_1t"] = res.get("score_1t", 0)
                    m["pct_1t_dom"] = res.get("pct_1t_dom", 0)
                    m["pct_1t_ext"] = res.get("pct_1t_ext", 0)
            except Exception:
                pass
        return m

    if scanned_results and analyze_pure_stats_20:
        print(f"📊 Enrichissement AdamChoi Score /100 pour les {len(scanned_results)} matchs scannés Unibet...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            scanned_results = list(ex.map(enrich_adamchoi, scanned_results))

    # ── Sélection 100% 2ème Mi-Temps la Plus Prolifique ──
    # Critères : score_2t >= 55% + total_goals >= 2.0 + mt2_odds entre @1.80 et @2.20
    s3_matches = []
    rejected_matches = []

    for r in scanned_results:
        s2t = r.get("score_2t", 0)
        mt2 = r.get("mt2_odds")
        goals = r.get("total_goals_brut", 0.0)

        if s2t >= 55 and goals >= 2.0 and mt2 and 1.80 <= mt2 <= 2.20:
            r["double_confirm"] = True
            r["triple_confirm"] = True
            s3_matches.append(r)
        else:
            reasons = []
            if s2t < 55: reasons.append(f"Score 2T faible ({s2t}% < 55%)")
            if goals < 2.0: reasons.append(f"Peu de buts ({goals:.1f} < 2.0)")
            if not mt2: reasons.append("Cote 2T non dispo")
            elif not (1.80 <= mt2 <= 2.20): reasons.append(f"Cote 2T hors plage (@{mt2})")
            r["rejection_reason"] = " · ".join(reasons) if reasons else "Non retenu"
            rejected_matches.append(r)

    s3_matches.sort(key=lambda x: x.get("score_2t", 0), reverse=True)

    hybrid_option_b_matches = s3_matches
    nb_triple = len(s3_matches)
    nb_double = 0
    nb_simple = 0
    print(f"⭐ Matchs validés 2T Prolifique (Score 2T >= 55%, Goals >= 2.0, Cote @1.80-2.20) : {len(s3_matches)} / {len(scanned_results)}")
    print(f"🚫 Matchs rejetés : {len(rejected_matches)}")

    all_o25 = [m["over25"] for m in scanned_results if m.get("over25") is not None]
    all_btts = [m["btts_oui"] for m in scanned_results if m.get("btts_oui") is not None]

    avg_all_o25 = round(sum(all_o25) / len(all_o25), 2) if all_o25 else 0.0
    avg_all_btts = round(sum(all_btts) / len(all_btts), 2) if all_btts else 0.0

    sel_o25 = [m["over25"] for m in s3_matches if m.get("over25") is not None]
    sel_btts = [m["btts_oui"] for m in s3_matches if m.get("btts_oui") is not None]

    avg_sel_o25 = round(sum(sel_o25) / len(sel_o25), 2) if sel_o25 else 0.0
    avg_sel_btts = round(sum(sel_btts) / len(sel_btts), 2) if sel_btts else 0.0

    print(f"Moyenne globale Over 2.5 ({len(all_o25)} matchs) : {avg_all_o25:.2f} (Retenus : {avg_sel_o25:.2f})")
    print(f"Moyenne globale BTTS Oui ({len(all_btts)} matchs) : {avg_all_btts:.2f} (Retenus : {avg_sel_btts:.2f})")

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
        "s3": {
            m["id"]: {
                "match": f"{m['dom']} - {m['ext']}",
                "league": m["league"],
                "date_str": m["date_str"],
                "val_btts": m.get("btts_oui"),
                "val_o25": m.get("over25"),
                "double": m.get("double_confirm", True),
                "ac_score": m.get("ac_score", 0),
            }
            for m in s3_matches
        }
    }

    prev_s3 = prev_state.get("s3", {})
    new_s3   = [v for k, v in curr_state["s3"].items() if k not in prev_s3]
    drop_s3  = [v for k, v in prev_s3.items() if k not in curr_state["s3"]]
    var_s3   = []
    for k, v in curr_state["s3"].items():
        if k in prev_s3:
            old_btts = prev_s3[k].get("val_btts")
            if old_btts and old_btts != v["val_btts"]:
                diff = round(v["val_btts"] - old_btts, 2)
                var_s3.append({**v, "old_btts": old_btts, "diff": diff})

    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(curr_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')

    # ── Bloc Évolutions HTML ─────────────────────────────────────────────────
    evo_html = ""
    if new_s3 or var_s3 or drop_s3:
        evo_html += '<div style="background:#fefce8; border:1px solid #fde68a; border-radius:8px; padding:15px; margin-bottom:25px;">'
        evo_html += '<h3 style="color:#92400e; margin-top:0; border-bottom:1px solid #fde68a; padding-bottom:5px;">📊 ÉVOLUTIONS DEPUIS LE DERNIER RUN (~2h)</h3>'

        if new_s3:
            evo_html += '<p style="color:#15803d; font-weight:bold; margin-bottom:5px;">🆕 Nouveaux matchs détectés :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in new_s3[:6]:
                badge = " ⭐⭐ DOUBLE" if item.get("double") else ""
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>{item['match']}</b> — BTTS Oui: <b>{item['val_btts']}</b>{badge}</li>"
            if len(new_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(new_s3) - 6} autres nouveaux matchs</li>"
            evo_html += '</ul>'

        if var_s3:
            evo_html += '<p style="color:#1d4ed8; font-weight:bold; margin-bottom:5px;">📈 Variations de cote BTTS Oui :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_s3[:6]:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : BTTS Oui {item['old_btts']} &rarr; <b>{item['val_btts']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            if len(var_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(var_s3) - 6} autres variations</li>"
            evo_html += '</ul>'

        if drop_s3:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Matchs sortis de la sélection :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_s3[:6]:
                evo_html += f"<li><b>{item['match']}</b> ({item['league']})</li>"
            if len(drop_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(drop_s3) - 6} autres matchs expirés ou écartés</li>"
            evo_html += '</ul>'

        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation depuis le dernier run.</div>'

    pen_simples = []   # Penalty supprimé
    pen_rejected = []  # Penalty supprimé

    def get_day_key(m_dt):
        return m_dt.astimezone(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")

    # Fenêtre de sélection : uniquement les matchs dans les 36 prochaines heures
    WINDOW_H = 36
    window_end = now_utc + timedelta(hours=WINDOW_H)

    # ── MOTEUR 1 : DOUBLÉS 2ÈME MI-TEMPS LA PLUS PROLIFIQUE (Cote >= 3.20) ──
    # Triple validation :
    # 1. score_2t >= 55%  → majorité nette des matchs récents ont 2T > 1T
    # 2. total_goals >= 2.0 → match offensif minimal
    # 3. mt2_odds entre @1.80 et @2.20 → valeur réelle
    MIN_2T_SCORE  = 55     # % matchs récents 2T > 1T
    MIN_2T_GOALS  = 2.0    # buts moyens totaux
    MIN_2T_ODDS   = 1.80   # Unibet → ~@1.75 réel tabac
    MAX_2T_ODDS   = 2.20   # plafond : marché trop incertain au-delà
    MIN_2T_COMBO  = 3.20   # cote combinée minimum

    mt2_pool = []
    for m in scanned_results:
        m_dt = m.get("dt_obj") or (datetime.fromisoformat(m["start_iso"].replace("Z", "+00:00")) if m.get("start_iso") else now_utc)
        if m_dt > window_end:          # hors fenêtre 36h → ignoré
            continue
        s2t   = m.get("score_2t", 0)
        mt2   = m.get("mt2_odds")
        goals = m.get("total_goals_brut", 0.0)
        if (s2t >= MIN_2T_SCORE
                and goals >= MIN_2T_GOALS
                and mt2 and MIN_2T_ODDS <= mt2 <= MAX_2T_ODDS):
            mt2_pool.append({"m": m, "id": m["id"], "dt": m_dt,
                             "day": get_day_key(m_dt), "odds": mt2, "score": s2t,
                             "goals": goals, "market": "🕐 2T Prolifique"})

    mt2_pool.sort(key=lambda x: (-x["score"], x["dt"]))

    # ── Pool 1T Prolifique ──
    MIN_1T_SCORE = 35
    MIN_1T_GOALS = 2.0
    MIN_1T_ODDS  = 2.30

    mt1_pool = []
    for m in scanned_results:
        m_dt = m.get("dt_obj") or (datetime.fromisoformat(m["start_iso"].replace("Z", "+00:00")) if m.get("start_iso") else now_utc)
        if m_dt > window_end:          # hors fenêtre 36h → ignoré
            continue
        s1t   = m.get("score_1t", 0)
        mt1   = m.get("mt1_odds")
        goals = m.get("total_goals_brut", 0.0)
        if (s1t >= MIN_1T_SCORE
                and goals >= MIN_1T_GOALS
                and mt1 and mt1 >= MIN_1T_ODDS):
            mt1_pool.append({"m": m, "id": m["id"], "dt": m_dt,
                             "day": get_day_key(m_dt), "odds": mt1, "score": s1t,
                             "goals": goals, "market": "⚡ 1T Prolifique"})

    mt2_pool.sort(key=lambda x: (-x["score"], x["dt"]))
    mt1_pool.sort(key=lambda x: (-x["score"], -x["odds"]))
    print(f"📊 Pool 2T: {len(mt2_pool)} matchs | Pool 1T: {len(mt1_pool)} matchs (fenêtre {WINDOW_H}h)")

    # ── MOTEUR DE SÉLECTIONS ET COMBINÉS HYBRIDES (1T + 2T) ─────────────────
    # Les used_* sont par catégorie (B, A, Hybrides, 2T, 1T simples)
    # Un match peut apparaître dans plusieurs catégories — pas de pool global épuisé.
    # Les items de chaque ticket sont toujours triés par ordre chronologique (dt).
    stake_sys = 1.00  # 1.00 € par combinaison -> 3.00 € par système 2/3 (Mise totale 3 €)

    MAX_SYS_B   = 6   # Systèmes 2/3 Type B [2x 1T + 1x 2T]
    MAX_SYS_A   = 6   # Systèmes 2/3 Type A [2x 2T + 1x 1T]
    MAX_HYB_DBL = 6   # Combinés Doublés Hybrides [1x 1T + 1x 2T]
    MAX_2T_DBL  = 8   # Combinés Doublés 2T Purs [2x 2T]
    MAX_1T_SMP  = 8   # Paris Simples 1T secs

    def sorted_by_dt(items):
        """Tri chronologique des items d'un ticket (heure de match croissante)."""
        return sorted(items, key=lambda x: x["dt"])

    # 1. SYSTÈMES 2/3 HYBRIDES TYPE B (2 Matchs 1ère MT + 1 Match 2ème MT)
    # Pool indépendant pour cette catégorie
    used_b = set()
    systems_23_b = []
    for _ in range(MAX_SYS_B):
        rem_1t = [s for s in mt1_pool if s["id"] not in used_b]
        rem_2t = [s for s in mt2_pool if s["id"] not in used_b]
        if len(rem_1t) >= 2 and len(rem_2t) >= 1:
            c1, c2 = rem_1t[0], rem_1t[1]
            avail_2t = [s for s in rem_2t if s["id"] not in (c1["id"], c2["id"])]
            if not avail_2t:
                break
            a = avail_2t[0]
            used_b.update([c1["id"], c2["id"], a["id"]])
            o_12 = round(c1["odds"] * c2["odds"], 2)
            o_1a = round(c1["odds"] * a["odds"], 2)
            o_2a = round(c2["odds"] * a["odds"], 2)
            min_g = round(stake_sys * min(o_12, o_1a, o_2a), 2)
            max_g = round(stake_sys * (o_12 + o_1a + o_2a), 2)
            all_days = sorted(set([c1["day"], c2["day"], a["day"]]))
            day_lbl = " / ".join(all_days)
            # Trier les 3 sélections dans l'ordre chronologique du match
            items_chron = sorted_by_dt([c1, c2, a])
            # Identifier les rôles dans l'ordre chronologique
            c1_chron = next(x for x in items_chron if x["market"] == "⚡ 1T Prolifique" and x["id"] == c1["id"])
            c2_chron = next(x for x in items_chron if x["market"] == "⚡ 1T Prolifique" and x["id"] == c2["id"])
            a_chron  = next(x for x in items_chron if x["market"] == "🕐 2T Prolifique" and x["id"] == a["id"])
            systems_23_b.append({
                "type": "2x 1T + 1x 2T", "day": day_lbl,
                "c1": c1_chron, "c2": c2_chron, "a": a_chron,
                "_items_chron": items_chron,  # liste ordonnée chron pour affichage
                "o_12": o_12, "o_1a": o_1a, "o_2a": o_2a,
                "stake_line": stake_sys, "stake_tot": round(stake_sys * 3, 2),
                "min_gain": min_g, "max_gain": max_g
            })
        else:
            break

    # 2. SYSTÈMES 2/3 HYBRIDES TYPE A (2 Matchs 2ème MT + 1 Match 1ère MT)
    # Pool indépendant pour cette catégorie
    used_a = set()
    systems_23_a = []
    for _ in range(MAX_SYS_A):
        rem_2t = [s for s in mt2_pool if s["id"] not in used_a]
        rem_1t = [s for s in mt1_pool if s["id"] not in used_a]
        if len(rem_2t) >= 2 and len(rem_1t) >= 1:
            a1, a2 = rem_2t[0], rem_2t[1]
            avail_1t = [s for s in rem_1t if s["id"] not in (a1["id"], a2["id"])]
            if not avail_1t:
                break
            c = avail_1t[0]
            used_a.update([a1["id"], a2["id"], c["id"]])
            o_12 = round(a1["odds"] * a2["odds"], 2)
            o_1c = round(a1["odds"] * c["odds"], 2)
            o_2c = round(a2["odds"] * c["odds"], 2)
            min_g = round(stake_sys * min(o_12, o_1c, o_2c), 2)
            max_g = round(stake_sys * (o_12 + o_1c + o_2c), 2)
            all_days = sorted(set([a1["day"], a2["day"], c["day"]]))
            day_lbl = " / ".join(all_days)
            # Tri chronologique des 3 sélections
            items_chron = sorted_by_dt([a1, a2, c])
            a1_chron = next(x for x in items_chron if x["market"] == "🕐 2T Prolifique" and x["id"] == a1["id"])
            a2_chron = next(x for x in items_chron if x["market"] == "🕐 2T Prolifique" and x["id"] == a2["id"])
            c_chron  = next(x for x in items_chron if x["market"] == "⚡ 1T Prolifique" and x["id"] == c["id"])
            systems_23_a.append({
                "type": "2x 2T + 1x 1T", "day": day_lbl,
                "a1": a1_chron, "a2": a2_chron, "c": c_chron,
                "_items_chron": items_chron,
                "o_12": o_12, "o_1c": o_1c, "o_2c": o_2c,
                "stake_line": stake_sys, "stake_tot": round(stake_sys * 3, 2),
                "min_gain": min_g, "max_gain": max_g
            })
        else:
            break

    # 3. COMBINÉS DOUBLÉS HYBRIDES (1 Match 1ère MT + 1 Match 2ème MT)
    # Pool indépendant — chaque match peut aussi être dans un système 2/3
    used_hyb = set()
    combos_hybrid = []
    for _ in range(MAX_HYB_DBL):
        rem_1t = [s for s in mt1_pool if s["id"] not in used_hyb]
        rem_2t = [s for s in mt2_pool if s["id"] not in used_hyb]
        if len(rem_1t) >= 1 and len(rem_2t) >= 1:
            c = rem_1t[0]
            avail_2t = [s for s in rem_2t if s["id"] != c["id"]]
            if not avail_2t:
                break
            a = avail_2t[0]
            used_hyb.update([c["id"], a["id"]])
            comb_o = round(c["odds"] * a["odds"], 2)
            all_days = sorted(set([c["day"], a["day"]]))
            day_lbl = " / ".join(all_days)
            # Tri chronologique : afficher les 2 matchs dans l'ordre horaire
            items_chron = sorted_by_dt([c, a])
            combos_hybrid.append({
                "type": "Doublé Hybride (1T + 2T)", "day": day_lbl,
                "items": items_chron,  # triés chronologiquement
                "comb_odds": comb_o, "stake": 3.0,
                "gain": round(3.0 * comb_o, 2), "profit": round(3.0 * comb_o - 3.0, 2)
            })
        else:
            break

    # 4. COMBINÉS DOUBLÉS 2T PURS (2 Matchs 2ème MT)
    # Pool indépendant
    used_2t_dbl = set()
    combos_2t_pure = []
    for _ in range(MAX_2T_DBL):
        rem_2t = [s for s in mt2_pool if s["id"] not in used_2t_dbl]
        if len(rem_2t) >= 2:
            a1, a2 = rem_2t[0], rem_2t[1]
            used_2t_dbl.update([a1["id"], a2["id"]])
            comb_o = round(a1["odds"] * a2["odds"], 2)
            all_days = sorted(set([a1["day"], a2["day"]]))
            day_lbl = " / ".join(all_days)
            # Tri chronologique des 2 matchs
            items_chron = sorted_by_dt([a1, a2])
            combos_2t_pure.append({
                "type": "Doublé 2T Prolifique", "day": day_lbl,
                "items": items_chron,  # triés chronologiquement
                "comb_odds": comb_o, "stake": 4.0,
                "gain": round(4.0 * comb_o, 2), "profit": round(4.0 * comb_o - 4.0, 2)
            })
        else:
            break

    # 5. PARIS SIMPLES 1T SECS (les pépites restantes, hors Formule B)
    simples_1t = [s for s in mt1_pool if s["id"] not in used_b][:MAX_1T_SMP]
    combos_mixed = combos_hybrid + combos_2t_pure

    print(f"🎲 Systèmes 2/3 Type B (2x 1T + 1x 2T) : {len(systems_23_b)}")
    print(f"🎲 Systèmes 2/3 Type A (2x 2T + 1x 1T) : {len(systems_23_a)}")
    print(f"⚡ Doublés Hybrides (1T + 2T)          : {len(combos_hybrid)}")
    print(f"🚀 Doublés 2T Purs (2x 2T)             : {len(combos_2t_pure)}")
    print(f"🎯 Simples 1T Secs                     : {len(simples_1t)}")



    def render_match_proof_html(m):
        score = m.get("ac_score", 0)
        # Pas de données AdamChoi pour ce match → ne pas afficher de bloc vide
        if not score:
            return '<div style="color:#94a3b8; font-size:11px; font-style:italic; margin-top:6px;">📭 Données AdamChoi non disponibles pour cette équipe.</div>'
        classe = m.get("ac_classe", "Bon potentiel")
        pts_ipo = m.get("pts_ipo", 0)
        ipo_val = m.get("ipo_comb", 0.0)
        pts_goals = m.get("pts_goals", 0)
        goals_val = m.get("total_goals_brut", 0.0)
        pts_freq = m.get("pts_freq", 0)
        freq_val = m.get("avg_freq_all", 0.0)
        pts_sot = m.get("pts_sot", 0)
        sot_val = m.get("sot_comb", 0.0)
        pts_ha = m.get("pts_ha", 0)
        ha_val = m.get("avg_freq_ha", 0.0)
        pts_league = m.get("pts_league", 0)

        if score >= 90:
            score_style = "background: linear-gradient(135deg, #dc2626, #ea580c); color: #ffffff;"
        elif score >= 85:
            score_style = "background: linear-gradient(135deg, #ea580c, #f59e0b); color: #ffffff;"
        elif score >= 80:
            score_style = "background: #f59e0b; color: #ffffff;"
        else:
            score_style = "background: #10b981; color: #ffffff;"

        rec_h = m.get("recent_h_dom", [])
        h_pills = []
        for rm in rec_h[:10]:
            hg = rm.get("homeGoals", rm.get("homeGoalsFt", 0))
            ag = rm.get("awayGoals", rm.get("awayGoalsFt", 0))
            tot = int(hg) + int(ag)
            if tot >= 3:
                h_pills.append(f'<span style="background:#dcfce7; color:#166534; font-weight:800; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #bbf7d0; display:inline-block; margin:1px;">{hg}-{ag} 🔥</span>')
            else:
                h_pills.append(f'<span style="background:#f1f5f9; color:#64748b; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #e2e8f0; display:inline-block; margin:1px;">{hg}-{ag}</span>')
        h_pills_html = " ".join(h_pills) if h_pills else '<span style="color:#94a3b8; font-style:italic;">Données indisponibles</span>'

        rec_a = m.get("recent_a_ext", [])
        a_pills = []
        for rm in rec_a[:10]:
            hg = rm.get("homeGoals", rm.get("homeGoalsFt", 0))
            ag = rm.get("awayGoals", rm.get("awayGoalsFt", 0))
            tot = int(hg) + int(ag)
            if tot >= 3:
                a_pills.append(f'<span style="background:#dcfce7; color:#166534; font-weight:800; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #bbf7d0; display:inline-block; margin:1px;">{hg}-{ag} 🔥</span>')
            else:
                a_pills.append(f'<span style="background:#f1f5f9; color:#64748b; font-weight:600; font-size:11px; padding:2px 6px; border-radius:4px; border:1px solid #e2e8f0; display:inline-block; margin:1px;">{hg}-{ag}</span>')
        a_pills_html = " ".join(a_pills) if a_pills else '<span style="color:#94a3b8; font-style:italic;">Données indisponibles</span>'

        return f'''
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; margin-top:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span style="font-weight:800; font-size:12px; color:#0f172a;">📊 AUDIT STATISTIQUE (BARÈME V2)</span>
                <span style="{score_style} font-weight:800; font-size:11px; padding:3px 10px; border-radius:12px; letter-spacing:0.3px;">
                    {score}/100 &bull; {classe}
                </span>
            </div>

            <div style="background:#eef2ff; padding:8px 10px; border-radius:6px; border:1px solid #c7d2fe; font-size:11px; color:#3730a3; margin-bottom:8px; line-height:1.6;">
                <b>🕐 Profil 2ème Mi-Temps</b> : <b>{m.get('score_2t', 0)}%</b> de matchs avec 2T &gt; 1T &nbsp;|&nbsp; 
                DOM : <b>{m.get('pct_2t_dom', 0)}%</b> &nbsp;|&nbsp; EXT : <b>{m.get('pct_2t_ext', 0)}%</b> &nbsp;|&nbsp; 
                Cote 2T : <b>@{m.get('mt2_odds', 0):.2f}</b>
            </div>

            <div style="background:#ffffff; padding:8px 10px; border-radius:6px; border:1px solid #e2e8f0; font-size:11px; color:#475569; margin-bottom:8px; line-height:1.6;">
                <b>1. IPO ({ipo_val:.2f})</b>: {pts_ipo}/25 &nbsp;|&nbsp; 
                <b>2. Buts ({goals_val:.1f}b)</b>: {pts_goals}/15 &nbsp;|&nbsp; 
                <b>3. Freq ({freq_val:.0f}%)</b>: {pts_freq}/20 &nbsp;|&nbsp; 
                <b>4. Tirs ({sot_val:.1f}t)</b>: {pts_sot}/10 &nbsp;|&nbsp; 
                <b>5. H/A ({ha_val:.0f}%)</b>: {pts_ha}/20 &nbsp;|&nbsp; 
                <b>6. Ligue</b>: {pts_league}/10
            </div>

            <div style="font-size:11px; color:#334155; line-height:1.6;">
                <div style="margin-bottom:6px;">
                    <b>🏠 10m Domicile ({m['dom']})</b> :<br>{h_pills_html}
                </div>
                <div>
                    <b>✈️ 10m Extérieur ({m['ext']})</b> :<br>{a_pills_html}
                </div>
            </div>
        </div>
        '''



    # ── Rendu HTML unifié — tous les tickets regroupés par jour ──────────────

    JOURS_FR = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]

    def fmt_match_dt(item):
        """Retourne 'Mer. 03/09 · 18h45' depuis item['dt'] (UTC → Paris)."""
        try:
            dt_paris = item["dt"].astimezone(timezone(timedelta(hours=2)))
            return f"{JOURS_FR[dt_paris.weekday()]} {dt_paris.strftime('%d/%m')} · {dt_paris.strftime('%Hh%M')}"
        except Exception:
            return "?"

    def day_label(day_key):
        """'2026-09-04' → 'Jeu. 04/09'"""
        try:
            from datetime import date as _date
            d = _date.fromisoformat(day_key)
            return f"{JOURS_FR[d.weekday()]} {d.strftime('%d/%m')}"
        except Exception:
            return day_key

    def ticket_sort_dt(tk):
        """Datetime du premier match (le plus tôt) d'un ticket pour tri chrono."""
        items = tk.get("_items", [])
        if items:
            return min(x["dt"] for x in items)
        return now_utc

    # ── Construire la liste unifiée de tous les tickets ───────────────────────
    all_tickets = []

    for t in systems_23_b:
        items = t.get("_items_chron", [t["c1"], t["c2"], t["a"]])
        all_tickets.append({"kind": "SYS_B", "data": t, "_items": items,
                            "_sort_dt": min(x["dt"] for x in items),
                            "_day": min(x["day"] for x in items)})

    for t in systems_23_a:
        items = t.get("_items_chron", [t["a1"], t["a2"], t["c"]])
        all_tickets.append({"kind": "SYS_A", "data": t, "_items": items,
                            "_sort_dt": min(x["dt"] for x in items),
                            "_day": min(x["day"] for x in items)})

    for t in combos_hybrid:
        items = t["items"]
        all_tickets.append({"kind": "DBL_HYB", "data": t, "_items": items,
                            "_sort_dt": min(x["dt"] for x in items),
                            "_day": min(x["day"] for x in items)})

    for t in combos_2t_pure:
        items = t["items"]
        all_tickets.append({"kind": "DBL_2T", "data": t, "_items": items,
                            "_sort_dt": min(x["dt"] for x in items),
                            "_day": min(x["day"] for x in items)})

    for s in simples_1t:
        all_tickets.append({"kind": "SMP_1T", "data": s, "_items": [s],
                            "_sort_dt": s["dt"], "_day": s["day"]})

    # Trier tous les tickets par heure du premier match
    all_tickets.sort(key=lambda x: x["_sort_dt"])

    # Grouper par jour
    from itertools import groupby
    from operator import itemgetter

    def render_match_row(item, override_badge=None):
        """Rendu d'une ligne match avec badge heure + type mi-temps."""
        m = item["m"]
        mkt = item.get("market", "")
        if "2T" in mkt:
            badge_bg, badge_cl, badge_txt = "#dbeafe", "#1e40af", f"🔵 2ème MT · {fmt_match_dt(item)}"
            inst = "Cocher : 2ème Mi-Temps la plus prolifique"
            score_lbl = f"Score 2T: <b>{item['score']}%</b>"
            border_cl, bg_cl = "#2563eb", "#eff6ff"
            cote_cl = "#1d4ed8"
        else:
            badge_bg, badge_cl, badge_txt = "#fef3c7", "#92400e", f"🟡 1ère MT · {fmt_match_dt(item)}"
            inst = "Cocher : 1ère Mi-Temps la plus prolifique"
            score_lbl = f"Score 1T: <b>{item['score']}%</b>"
            border_cl, bg_cl = "#d97706", "#fffbeb"
            cote_cl = "#b45309"
        if override_badge:
            badge_txt = override_badge
        return f'''
        <div style="background:{bg_cl}; border:1px solid {badge_bg}; border-left:4px solid {border_cl}; padding:7px 10px; margin-bottom:5px; border-radius:5px; font-size:11px;">
          <div style="font-size:10px; font-weight:700; color:{badge_cl}; background:{badge_bg}; display:inline-block; padding:1px 7px; border-radius:4px; margin-bottom:4px;">{badge_txt}</div>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span><b>{m['dom']} vs {m['ext']}</b> <span style="color:#64748b; font-size:10px;">({m.get('league','')})</span></span>
            <span style="font-size:13px; font-weight:900; color:{cote_cl}; background:#fff; padding:1px 6px; border-radius:4px; border:1px solid {badge_bg};">@{item['odds']:.2f}</span>
          </div>
          <div style="display:flex; justify-content:space-between; color:{badge_cl}; font-size:10px; margin-top:2px;">
            <span>👉 <b>{inst}</b></span>
            <span>{score_lbl}</span>
          </div>
        </div>'''

    def render_ticket(tk, idx):
        kind = tk["kind"]
        t = tk["data"]

        if kind in ("SYS_B", "SYS_A"):
            # Système 2/3
            items = tk["_items"]
            stake_sys = t["stake_line"]
            tot_st = t["stake_tot"]
            if kind == "SYS_B":
                type_lbl = "2x 1ère MT + 1x 2ème MT"
                o1_lbl, o2_lbl, o3_lbl = "1T+1T", "1T+2T", "1T+2T"
                o_a, o_b, o_c = t["o_12"], t["o_1a"], t["o_2a"]
                hdr_bg, hdr_cl, bord = "#ede9fe", "#6d28d9", "#7c3aed"
            else:
                type_lbl = "2x 2ème MT + 1x 1ère MT"
                o1_lbl, o2_lbl, o3_lbl = "2T+2T", "2T+1T", "2T+1T"
                o_a, o_b, o_c = t["o_12"], t["o_1c"], t["o_2c"]
                hdr_bg, hdr_cl, bord = "#dbeafe", "#1e40af", "#2563eb"
            min_g, max_g = t["min_gain"], t["max_gain"]
            prof_min = round(min_g - tot_st, 2)
            prof_max = round(max_g - tot_st, 2)
            rows_html = "".join(render_match_row(i) for i in items)
            return f'''
            <div style="background:#fff; border:1.5px solid {hdr_bg}; border-left:5px solid {bord}; border-radius:10px; padding:12px 14px; margin-bottom:14px; box-shadow:0 2px 6px rgba(0,0,0,0.03);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:{hdr_bg}; padding:7px 12px; border-radius:6px; margin-bottom:9px; border:1px solid {hdr_bg};">
                <span style="font-weight:900; color:{hdr_cl}; font-size:13px;">🎟️ SYSTÈME 2/3 #{idx} — {type_lbl}</span>
                <span style="font-size:11px; font-weight:800; background:#dcfce7; color:#15803d; padding:3px 9px; border-radius:5px; border:1px solid #86efac;">Mise {tot_st:.2f} € (3 × {stake_sys:.2f} €)</span>
              </div>
              {rows_html}
              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:11px; margin-top:6px;">
                <div style="color:#475569; margin-bottom:4px;">
                  Combinaisons : Ticket 1 ({o1_lbl}): <b>@{o_a:.2f}</b> · Ticket 2 ({o2_lbl}): <b>@{o_b:.2f}</b> · Ticket 3 ({o3_lbl}): <b>@{o_c:.2f}</b>
                </div>
                <div style="display:flex; justify-content:space-between; border-top:1px dashed #cbd5e1; padding-top:5px;">
                  <span style="color:#15803d; font-weight:800;">🛡️ Remboursé dès 2/3 : <b>{min_g:.2f} €</b> <span style="font-size:10px;">(+{prof_min:.2f} € net)</span></span>
                  <span style="color:{hdr_cl}; font-weight:900; font-size:13px;">🏆 3/3 : <b>{max_g:.2f} €</b> <span style="font-size:10px; color:#15803d;">(+{prof_max:.2f} €)</span></span>
                </div>
              </div>
            </div>'''

        elif kind == "DBL_HYB":
            items = tk["_items"]
            cote = t["comb_odds"]
            gain = t["gain"]
            profit = t["profit"]
            rows_html = "".join(render_match_row(i) for i in items)
            return f'''
            <div style="background:#fff; border:1.5px solid #fed7aa; border-left:5px solid #ea580c; border-radius:10px; padding:11px 13px; margin-bottom:12px; box-shadow:0 1px 5px rgba(0,0,0,0.03);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:#fff7ed; padding:6px 10px; border-radius:6px; margin-bottom:8px; border:1px solid #fed7aa;">
                <span style="font-weight:900; color:#c2410c; font-size:12px;">⚡ DOUBLÉ HYBRIDE #{idx} — 1ère MT + 2ème MT</span>
                <span style="font-size:11px; font-weight:800; background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:4px; border:1px solid #86efac;">Cote @{cote:.2f} · Mise 3 € → {gain:.2f} € (+{profit:.2f} €)</span>
              </div>
              {rows_html}
            </div>'''

        elif kind == "DBL_2T":
            items = tk["_items"]
            cote = t["comb_odds"]
            gain = t["gain"]
            profit = t["profit"]
            rows_html = "".join(render_match_row(i) for i in items)
            return f'''
            <div style="background:#fff; border:1.5px solid #bfdbfe; border-left:5px solid #2563eb; border-radius:10px; padding:11px 13px; margin-bottom:12px; box-shadow:0 1px 5px rgba(0,0,0,0.03);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:#eff6ff; padding:6px 10px; border-radius:6px; margin-bottom:8px; border:1px solid #bfdbfe;">
                <span style="font-weight:900; color:#1e40af; font-size:12px;">🚀 DOUBLÉ 2T PUR #{idx} — 2ème MT + 2ème MT</span>
                <span style="font-size:11px; font-weight:800; background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:4px; border:1px solid #86efac;">Cote @{cote:.2f} · Mise 4 € → {gain:.2f} € (+{profit:.2f} €)</span>
              </div>
              {rows_html}
            </div>'''

        else:  # SMP_1T
            s = t
            m = s["m"]
            dt_lbl = fmt_match_dt(s)
            return f'''
            <div style="background:#fffbeb; border:1px solid #fde68a; border-left:4px solid #b45309; border-radius:8px; padding:8px 12px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <div>
                <div style="font-size:10px; font-weight:700; color:#92400e; background:#fef3c7; display:inline-block; padding:1px 7px; border-radius:4px; margin-bottom:3px;">⚡ SIMPLE 1T #{idx} · {dt_lbl}</div>
                <b style="font-size:12px; color:#0f172a;">{m['dom']} vs {m['ext']}</b>
                <span style="font-size:10px; color:#64748b;"> ({m.get('league','')})</span><br>
                <span style="font-size:11px; color:#92400e;">👉 <b>1ère MT prolifique</b> · Score 1T: <b>{s['score']}%</b> · Moy. buts: {s['goals']:.1f}</span>
              </div>
              <div style="text-align:right; min-width:90px;">
                <div style="font-size:15px; font-weight:900; color:#b45309;">@{s['odds']:.2f}</div>
                <span style="font-size:10px; background:#dcfce7; color:#15803d; font-weight:700; padding:2px 6px; border-radius:4px;">Mise 3 € → {3.0*s['odds']:.2f} €</span>
              </div>
            </div>'''

    # ── Rendu final regroupé par jour ─────────────────────────────────────────
    systems_23_html = ""
    combos_hybrid_html = ""
    combos_2t_html = ""
    simples_1t_html = ""

    # Une seule section unifiée
    unified_html = ""
    idx_by_kind = {"SYS_B": 0, "SYS_A": 0, "DBL_HYB": 0, "DBL_2T": 0, "SMP_1T": 0}

    # Grouper par jour (clé = day_key '2026-09-04')
    days_seen = []
    day_groups = {}
    for tk in all_tickets:
        dk = tk["_day"]
        if dk not in day_groups:
            day_groups[dk] = []
            days_seen.append(dk)
        day_groups[dk].append(tk)

    for dk in days_seen:
        unified_html += f'<div style="font-size:13px; font-weight:900; color:#0f172a; background:#f1f5f9; padding:8px 12px; border-radius:7px; margin:16px 0 10px 0; border-left:5px solid #6366f1;">📅 {day_label(dk)}</div>'
        for tk in day_groups[dk]:
            kind = tk["kind"]
            idx_by_kind[kind] += 1
            unified_html += render_ticket(tk, idx_by_kind[kind])

    if not unified_html:
        unified_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:20px;">Aucun ticket généré sur cette session.</div>'



    # ── Tableau chronologique de tous les matchs à jouer ─────────────────────
    plan_rows = []
    seen_plan = set()



    # ── Tableau chronologique de tous les matchs à jouer ─────────────────────
    plan_rows = []
    seen_plan = set()

    # Matchs des Systèmes 2/3 Type B (2x 1T + 1x 2T)
    for idx_sys, sys_item in enumerate(systems_23_b, 1):
        for role, item, mkt, bg, cl in [
            ("1T", sys_item["c1"], sys_item["c1"]["market"], "#fef3c7", "#92400e"),
            ("1T", sys_item["c2"], sys_item["c2"]["market"], "#fef3c7", "#92400e"),
            ("2T", sys_item["a"], sys_item["a"]["market"], "#e0e7ff", "#3730a3")
        ]:
            m = item["m"]
            key = (m["id"], mkt, f"SYSB_{idx_sys}")
            if key not in seen_plan:
                plan_rows.append({
                    "dt": item["dt"], "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}", "league": m.get("league", ""),
                    "market": item["market"], "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}%", "score_val": item["score"],
                    "type_label": f"SYS 2/3 #{idx_sys} ({role})",
                    "bg_market": bg, "cl_market": cl,
                })
                seen_plan.add(key)

    # Matchs des Systèmes 2/3 Type A (2x 2T + 1x 1T)
    for idx_sys, sys_item in enumerate(systems_23_a, 1):
        for role, item, mkt, bg, cl in [
            ("2T", sys_item["a1"], sys_item["a1"]["market"], "#e0e7ff", "#3730a3"),
            ("2T", sys_item["a2"], sys_item["a2"]["market"], "#e0e7ff", "#3730a3"),
            ("1T", sys_item["c"], sys_item["c"]["market"], "#fef3c7", "#92400e")
        ]:
            m = item["m"]
            key = (m["id"], mkt, f"SYSA_{idx_sys}")
            if key not in seen_plan:
                plan_rows.append({
                    "dt": item["dt"], "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}", "league": m.get("league", ""),
                    "market": item["market"], "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}%", "score_val": item["score"],
                    "type_label": f"SYS 2/3 A#{idx_sys} ({role})",
                    "bg_market": bg, "cl_market": cl,
                })
                seen_plan.add(key)

    # Doublés Hybrides
    for idx_hyb, ch in enumerate(combos_hybrid, 1):
        for item in ch["items"]:
            m = item["m"]
            key = (m["id"], item["market"], f"HYB_{idx_hyb}")
            if key not in seen_plan:
                is_1t = "1T" in item["market"]
                plan_rows.append({
                    "dt": item["dt"], "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}", "league": m.get("league", ""),
                    "market": item["market"], "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}%", "score_val": item["score"],
                    "type_label": f"DOUBLÉ HYBRIDE #{idx_hyb}",
                    "bg_market": "#fef3c7" if is_1t else "#e0e7ff",
                    "cl_market": "#92400e" if is_1t else "#3730a3",
                })
                seen_plan.add(key)

    # Doublés 2T Purs
    for idx_cb, cb in enumerate(combos_2t_pure, 1):
        for item in cb["items"]:
            m = item["m"]
            key = (m["id"], item["market"], f"DBL2T_{idx_cb}")
            if key not in seen_plan:
                plan_rows.append({
                    "dt": item["dt"], "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}", "league": m.get("league", ""),
                    "market": item["market"], "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}%", "score_val": item["score"],
                    "type_label": f"DOUBLÉ 2T #{idx_cb}",
                    "bg_market": "#e0e7ff", "cl_market": "#3730a3",
                })
                seen_plan.add(key)

    # Simples 1T restants
    for idx_s, s in enumerate(simples_1t, 1):
        m = s["m"]
        key = (m["id"], "1T_SIMPLE")
        if key not in seen_plan:
            plan_rows.append({
                "dt": s["dt"], "date_str": m.get("date_str", ""),
                "match": f"{m['dom']} vs {m['ext']}", "league": m.get("league", ""),
                "market": "⚡ 1T Prolifique", "cote": f"@{s['odds']:.2f}",
                "score_label": f"{s['score']}%", "score_val": s["score"],
                "type_label": f"SIMPLE 1T #{idx_s}",
                "bg_market": "#fffbeb", "cl_market": "#b45309",
            })
            seen_plan.add(key)

    plan_rows.sort(key=lambda x: x["dt"])

    # Génération HTML des lignes du planning
    plan_rows_html = ""
    for pr in plan_rows:
        sv = pr["score_val"]
        sc_bg = "#dc2626" if sv >= 90 else ("#ea580c" if sv >= 85 else ("#f59e0b" if sv >= 80 else ("#10b981" if sv >= 70 else "#6366f1")))
        plan_rows_html += (
            f'<tr>'
            f'<td style="padding:9px 8px; white-space:nowrap; font-weight:700; font-size:12px; color:#0f172a; border-bottom:1px solid #f1f5f9;">'
            f'{pr["date_str"]}</td>'
            f'<td style="padding:9px 8px; border-bottom:1px solid #f1f5f9;">'
            f'<b style="font-size:12px; color:#0f172a;">{pr["match"]}</b><br>'
            f'<span style="font-size:10px; color:#94a3b8;">{pr["league"]}</span></td>'
            f'<td style="padding:9px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">'
            f'<span style="background:{pr["bg_market"]}; color:{pr["cl_market"]}; font-weight:700; font-size:11px; padding:3px 7px; border-radius:5px; white-space:nowrap;">'
            f'{pr["market"]}</span></td>'
            f'<td style="padding:9px 6px; text-align:center; font-weight:900; font-size:13px; color:#0f172a; border-bottom:1px solid #f1f5f9;">{pr["cote"]}</td>'
            f'<td style="padding:9px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">'
            f'<span style="background:{sc_bg}; color:#fff; font-weight:800; font-size:11px; padding:3px 7px; border-radius:5px;">'
            f'{pr["score_label"]}</span></td>'
            f'<td style="padding:9px 6px; text-align:center; font-size:11px; font-weight:700; color:#475569; border-bottom:1px solid #f1f5f9;">{pr["type_label"]}</td>'
            f'</tr>'
        )
    if not plan_rows_html:
        plan_rows_html = '<tr><td colspan="6" style="padding:20px; text-align:center; color:#94a3b8; font-style:italic;">Aucun match retenu sur le créneau à venir.</td></tr>'

    # ── Tableau compact des matchs analysés/rejetés ──────────────────────────
    scan_rows_html = ""
    for m in sorted(scanned_results, key=lambda x: max(x.get("score_2t", 0), x.get("score_1t", 0)), reverse=True):
        retained = (m in s3_matches) or any(m["id"] == s["id"] for s in mt1_pool)
        bg_row = "#f0fdf4" if retained else "#fff"
        badge = '<span style="color:#15803d; font-weight:700;">✅ RETENU</span>' if retained else '<span style="color:#94a3b8;">—</span>'
        mt2 = f"@{m['mt2_odds']:.2f}" if m.get("mt2_odds") else "N/A"
        mt1 = f"@{m['mt1_odds']:.2f}" if m.get("mt1_odds") else "N/A"
        s2t_v = m.get("score_2t", 0)
        s1t_v = m.get("score_1t", 0)
        goals_v = m.get("total_goals_brut", 0.0)
        
        # Badges
        s2t_bg = "#dcfce7" if s2t_v >= 65 else ("#fef3c7" if s2t_v >= 55 else "#fee2e2")
        s2t_cl = "#15803d" if s2t_v >= 65 else ("#92400e" if s2t_v >= 55 else "#dc2626")
        s2t_badge = f'<span style="background:{s2t_bg}; color:{s2t_cl}; font-weight:800; font-size:11px; padding:2px 6px; border-radius:5px;">{s2t_v}%</span>' if s2t_v > 0 else '<span style="color:#94a3b8;">—</span>'

        s1t_bg = "#fef3c7" if s1t_v >= 35 else "#f1f5f9"
        s1t_cl = "#92400e" if s1t_v >= 35 else "#64748b"
        s1t_badge = f'<span style="background:{s1t_bg}; color:{s1t_cl}; font-weight:800; font-size:11px; padding:2px 6px; border-radius:5px;">{s1t_v}%</span>' if s1t_v > 0 else '<span style="color:#94a3b8;">—</span>'

        goals_badge = f'<span style="font-size:11px; font-weight:700; color:#334155;">{goals_v:.1f}b</span>' if goals_v > 0 else '<span style="color:#94a3b8;">—</span>'

        scan_rows_html += (
            f'<tr style="background:{bg_row};">'
            f'<td style="padding:7px 8px; font-size:11px; color:#475569; border-bottom:1px solid #f1f5f9;">{m.get("date_str", "")}</td>'
            f'<td style="padding:7px 8px; font-size:12px; font-weight:700; color:#0f172a; border-bottom:1px solid #f1f5f9;">{m.get("dom", "")} vs {m.get("ext", "")}'
            f'<br><span style="font-size:10px; color:#94a3b8; font-weight:400;">{m.get("league", "")}</span></td>'
            f'<td style="padding:7px 4px; text-align:center; border-bottom:1px solid #f1f5f9;">{s2t_badge}</td>'
            f'<td style="padding:7px 4px; text-align:center; border-bottom:1px solid #f1f5f9;">{s1t_badge}</td>'
            f'<td style="padding:7px 4px; text-align:center; border-bottom:1px solid #f1f5f9;">{goals_badge}</td>'
            f'<td style="padding:7px 4px; text-align:center; font-weight:800; font-size:12px; color:#1e40af; border-bottom:1px solid #f1f5f9;">{mt2}</td>'
            f'<td style="padding:7px 4px; text-align:center; font-weight:800; font-size:12px; color:#b45309; border-bottom:1px solid #f1f5f9;">{mt1}</td>'
            f'<td style="padding:7px 4px; text-align:center; font-size:11px; border-bottom:1px solid #f1f5f9;">{badge}</td>'
            f'</tr>'
        )

    # ── Email HTML Nouveau Design ─────────────────────────────────────────────
    now_local = datetime.now(timezone(timedelta(hours=2)))
    days_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    date_header = now_local.strftime(f"{days_fr[now_local.weekday()]} %d/%m/%Y · %Hh%M")
    tot_sys = len(systems_23_b) + len(systems_23_a)
    tot_hyb_dbl = len(combos_hybrid)
    tot_2t_dbl = len(combos_2t_pure)
    tot_smp_1t = len(simples_1t)

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
      <body style="font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif; background:#f1f5f9; margin:0; padding:12px; color:#1e293b;">
        <div style="max-width:700px; margin:0 auto; background:#ffffff; border-radius:14px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">

          <!-- HEADER -->
          <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%); padding:22px 24px; text-align:center;">
            <div style="font-size:10px; letter-spacing:2px; text-transform:uppercase; color:#94a3b8; margin-bottom:6px;">⚽ FOOTBALL PREMIUM · UNIBET FRANCE</div>
            <h1 style="margin:0; font-size:21px; font-weight:900; color:#ffffff;">{date_header}</h1>
            <p style="margin:7px 0 0 0; font-size:11px; color:#cbd5e1;">Tickets Hybrides Mi-Temps Prolifiques (1T / 2T) · Systèmes 2/3 & Doublés · {now_str}</p>
          </div>

          <!-- COMPTEURS -->
          <div style="background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:12px 14px;">
            <table style="width:100%; border-collapse:collapse; text-align:center;">
              <tr>
                <td style="padding:0 3px;"><div style="background:#ede9fe; border-radius:8px; padding:8px 4px;"><div style="font-size:20px; font-weight:900; color:#6d28d9;">{tot_sys}</div><div style="font-size:9px; font-weight:700; color:#6d28d9;">SYSTÈMES 2/3</div><div style="font-size:9px; color:#7c3aed;">1T & 2T Hybrides</div></div></td>
                <td style="padding:0 3px;"><div style="background:#ffedd5; border-radius:8px; padding:8px 4px;"><div style="font-size:20px; font-weight:900; color:#c2410c;">{tot_hyb_dbl}</div><div style="font-size:9px; font-weight:700; color:#c2410c;">DOUBLÉS HYBRIDES</div><div style="font-size:9px; color:#ea580c;">Cotes @5.00+</div></div></td>
                <td style="padding:0 3px;"><div style="background:#dbeafe; border-radius:8px; padding:8px 4px;"><div style="font-size:20px; font-weight:900; color:#1d4ed8;">{tot_2t_dbl}</div><div style="font-size:9px; font-weight:700; color:#1d4ed8;">DOUBLÉS 2T</div><div style="font-size:9px; color:#3b82f6;">Cotes @3.50+</div></div></td>
                <td style="padding:0 3px;"><div style="background:#fef3c7; border-radius:8px; padding:8px 4px;"><div style="font-size:20px; font-weight:900; color:#b45309;">{tot_smp_1t}</div><div style="font-size:9px; font-weight:700; color:#b45309;">SIMPLES 1T</div><div style="font-size:9px; color:#d97706;">Cotes @2.50+</div></div></td>
              </tr>
            </table>
          </div>

          <!-- SECTION 1 : PLANNING HEURE PAR HEURE -->
          <div style="padding:16px 16px 8px 16px;">
            <div style="font-size:14px; font-weight:900; color:#0f172a; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <span>📅 CE QUE VOUS DEVEZ JOUER — HEURE PAR HEURE</span>
              <span style="font-size:11px; background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:6px;">{len(plan_rows)} pari(s)</span>
            </div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <thead><tr style="background:#0f172a; color:#ffffff; font-size:10px; text-transform:uppercase; font-weight:700;">
                  <th style="padding:9px 8px; text-align:left; white-space:nowrap;">Heure</th>
                  <th style="padding:9px 8px; text-align:left;">Match</th>
                  <th style="padding:9px 6px; text-align:center; min-width:100px;">Marché</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Cote</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Score</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Type</th>
                </tr></thead>
                <tbody>{plan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- EVOLUTIONS -->
          <div style="padding:0 16px 8px 16px;">{evo_html}</div>


          <!-- TICKETS PAR JOUR — tous types regroupés chronologiquement -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🎟️ TICKETS À JOUER &nbsp;<span style="font-size:12px; font-weight:600; color:#64748b;">— regroupés par jour, dans l'ordre chronologique</span></span>
              <span style="font-size:11px; background:#e0e7ff; color:#4338ca; padding:2px 8px; border-radius:6px; font-weight:700;">{len(all_tickets)} ticket(s)</span>
            </div>
            {unified_html}
          </div>

          <!-- SECTION 6 : TOUS LES MATCHS ANALYSÉS -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:13px; font-weight:800; color:#475569; margin-bottom:8px;">📊 TOUS LES MATCHS ANALYSÉS ({len(scanned_results)} scannés)</div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <thead><tr style="background:#f1f5f9; color:#64748b; font-size:10px; text-transform:uppercase; font-weight:700; border-bottom:1px solid #e2e8f0;">
                  <th style="padding:7px 8px; text-align:left;">Heure</th>
                  <th style="padding:7px 8px; text-align:left;">Match</th>
                  <th style="padding:7px 4px; text-align:center;">Score 2T</th>
                  <th style="padding:7px 4px; text-align:center;">Score 1T</th>
                  <th style="padding:7px 4px; text-align:center;">Buts Moy.</th>
                  <th style="padding:7px 4px; text-align:center;">Cote 2T</th>
                  <th style="padding:7px 4px; text-align:center;">Cote 1T</th>
                  <th style="padding:7px 4px; text-align:center;">Statut</th>
                </tr></thead>
                <tbody>{scan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- FOOTER -->
          <div style="padding:12px 20px; background:#0f172a; font-size:10px; color:#64748b; text-align:center;">
            ⚠️ Paris sportifs · Jouez avec modération · Analyse 100% AdamChoi Mi-Temps Prolifiques · Unibet France · {now_str}
          </div>

        </div>
      </body>
    </html>
    """

    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ SÉLECTION SYSTÈMES 2/3 HYBRIDES & DOUBLÉS PROLIFIQUES",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}",
        f"**Systèmes 2/3 Hybrides** : Formules [2x 1T + 1x 2T] et [2x 2T + 1x 1T] · Mise 3.00 € (3 x 1.00 €)",
        f"**Règle de remboursement** : Remboursé avec profit garanti dès 2 bons résultats sur 3 (Cotes combinées >= 3.50)\n",
    ]

    if systems_23_b:
        report.append(f"## 🔥 Systèmes 2/3 Formule B (2x 1T + 1x 2T — {len(systems_23_b)} tickets — Mise 3.00 € / système)\n")
        for idx_b, sb in enumerate(systems_23_b, 1):
            c1, c2, a = sb["c1"]["m"], sb["c2"]["m"], sb["a"]["m"]
            report.append(f"### Système 2/3 Formule B #{idx_b} — {sb['day']} | Mise: 3.00 € → Gain Min (2/3): `{sb['min_gain']:.2f} €` | Gain Max (3/3): `{sb['max_gain']:.2f} €`")
            report.append(f"- **🟡 1ère MT #1** : `{c1['date_str']}` — **{c1['dom']} vs {c1['ext']}** (@`{sb['c1']['odds']:.2f}`) — Score 1T: {sb['c1']['score']}%")
            report.append(f"- **🟡 1ère MT #2** : `{c2['date_str']}` — **{c2['dom']} vs {c2['ext']}** (@`{sb['c2']['odds']:.2f}`) — Score 1T: {sb['c2']['score']}%")
            report.append(f"- **🔵 2ème MT** : `{a['date_str']}` — **{a['dom']} vs {a['ext']}** (@`{sb['a']['odds']:.2f}`) — Score 2T: {sb['a']['score']}%")
            report.append(f"- *Combinaisons* : 1T+1T: @`{sb['o_12']:.2f}` | 1T+2T: @`{sb['o_1a']:.2f}` | 1T+2T: @`{sb['o_2a']:.2f}`\n")

    if systems_23_a:
        report.append(f"## 🛡️ Systèmes 2/3 Formule A (2x 2T + 1x 1T — {len(systems_23_a)} tickets — Mise 3.00 € / système)\n")
        for idx_a, sa in enumerate(systems_23_a, 1):
            a1, a2, c = sa["a1"]["m"], sa["a2"]["m"], sa["c"]["m"]
            report.append(f"### Système 2/3 Formule A #{idx_a} — {sa['day']} | Mise: 3.00 € → Gain Min (2/3): `{sa['min_gain']:.2f} €` | Gain Max (3/3): `{sa['max_gain']:.2f} €`")
            report.append(f"- **🔵 2ème MT #1** : `{a1['date_str']}` — **{a1['dom']} vs {a1['ext']}** (@`{sa['a1']['odds']:.2f}`) — Score 2T: {sa['a1']['score']}%")
            report.append(f"- **🔵 2ème MT #2** : `{a2['date_str']}` — **{a2['dom']} vs {a2['ext']}** (@`{sa['a2']['odds']:.2f}`) — Score 2T: {sa['a2']['score']}%")
            report.append(f"- **🟡 1ère MT** : `{c['date_str']}` — **{c['dom']} vs {c['ext']}** (@`{sa['c']['odds']:.2f}`) — Score 1T: {sa['c']['score']}%")
            report.append(f"- *Combinaisons* : 2T+2T: @`{sa['o_12']:.2f}` | 2T+1T: @`{sa['o_1c']:.2f}` | 2T+1T: @`{sa['o_2c']:.2f}`\n")

    if combos_hybrid:
        report.append(f"## ⚡ Combinés Doublés Hybrides (1T + 2T — {len(combos_hybrid)} tickets — Cotes @5.00+ — Mise 3.00 €)\n")
        for idx_h, ch in enumerate(combos_hybrid, 1):
            c, a = ch["items"][0]["m"], ch["items"][1]["m"]
            report.append(f"### Doublé Hybride #{idx_h} — Cote Totale: `{ch['comb_odds']:.2f}` | Mise 3 € → Gain: `{ch['gain']:.2f} €` *(+{ch['profit']:.2f} € net)*")
            report.append(f"- **🟡 1ère MT** : `{c['date_str']}` — **{c['dom']} vs {c['ext']}** (@`{ch['items'][0]['odds']:.2f}`) — Score 1T: {ch['items'][0]['score']}%")
            report.append(f"- **🔵 2ème MT** : `{a['date_str']}` — **{a['dom']} vs {a['ext']}** (@`{ch['items'][1]['odds']:.2f}`) — Score 2T: {ch['items'][1]['score']}%")
            report.append("")

    if combos_2t_pure:
        report.append(f"## 🚀 Combinés Doublés 2T Purs ({len(combos_2t_pure)} tickets — Cotes @3.50+ — Mise 4.00 €)\n")
        for idx, cb in enumerate(combos_2t_pure, 1):
            a1, a2 = cb["items"][0]["m"], cb["items"][1]["m"]
            report.append(f"### Doublé 2T #{idx} — Cote Totale: `{cb['comb_odds']:.2f}` | Mise 4 € → Gain: `{cb['gain']:.2f} €` *(+{cb['profit']:.2f} € net)*")
            report.append(f"- **🔵 2ème MT #1** : `{a1['date_str']}` — **{a1['dom']} vs {a1['ext']}** (@`{cb['items'][0]['odds']:.2f}`) — Score 2T: {cb['items'][0]['score']}%")
            report.append(f"- **🔵 2ème MT #2** : `{a2['date_str']}` — **{a2['dom']} vs {a2['ext']}** (@`{cb['items'][1]['odds']:.2f}`) — Score 2T: {cb['items'][1]['score']}%")
            report.append("")

    if simples_1t:
        report.append(f"## 🎯 Paris Simples 1T Restants ({len(simples_1t)} matchs — Mise 3.00 €)\n")
        for idx_s, s in enumerate(simples_1t, 1):
            m = s["m"]
            report.append(f"- **Simple 1T #{idx_s}** : `{m['date_str']}` — **{m['dom']} vs {m['ext']}** (@`{s['odds']:.2f}`) — Score 1T: **{s['score']}%** (Moy. buts: {s['goals']:.1f}b)")
        report.append("")

    report.append("## ✅ Matchs Candidats 2T & 1T")
    report.append("| Date | Ligue | Match | Score 2T | Score 1T | Buts Moy. | Cote 2T | Cote 1T |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
    for m in s3_matches:
        mt2_str = f"@{m['mt2_odds']:.2f}" if m.get("mt2_odds") else "N/A"
        mt1_str = f"@{m['mt1_odds']:.2f}" if m.get("mt1_odds") else "N/A"
        report.append(f"| {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{m.get('score_2t', 0)}%** | **{m.get('score_1t', 0)}%** | **{m.get('total_goals_brut', 0):.1f}** | **{mt2_str}** | **{mt1_str}** |")

    report.append(f"\n## 🚫 Matchs Non Retenus ({len(rejected_matches)})\n")
    report.append("| Date | Ligue | Match | Score 2T | Buts | Raison du Rejet |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :--- |")
    for m in rejected_matches:
        reason = m.get("rejection_reason", "Non éligible")
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | {m.get('score_2t', 0)}% | {m.get('total_goals_brut', 0):.1f} | {reason} |")

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

    nb_s3 = len(s3_matches)
    now_dt = datetime.now(timezone.utc)
    subject_date = now_dt.strftime('%d/%m %Hh%M')
    raw_subject = f"⚽ Football {subject_date} — {tot_sys} Systèmes 2/3 Hybrides · {tot_hyb_dbl} Doublés Hybrides · {tot_2t_dbl} Doublés 2T"
    
    # Nettoyage ASCII du sujet pour compatibilité maximale MTA
    clean_subject = unicodedata.normalize('NFKD', raw_subject).encode('ASCII', 'ignore').decode('ASCII')
    if not clean_subject.strip():
        clean_subject = f"Rapport foot du {subject_date} - {nb_s3} matchs retenus"

    msg = EmailMessage(policy=email.policy.SMTPUTF8)
    msg["Subject"] = clean_subject
    msg["From"] = f"Gregory LANGLET <{gmail_email}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(html_body, subtype="html", charset="utf-8")

    sent_success = False

    # Tentative Gmail SMTP prioritaire avec as_bytes() (Règle GitHub-Actions)
    if gmail_password:
        try:
            print(f"Sending email to {recipients} via Gmail SMTP (SMTPUTF8)...")
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(gmail_email, gmail_password)
                server.sendmail(gmail_email, recipients, msg.as_bytes())
            print("SUCCESS! Email sent via Gmail SMTP.")
            sent_success = True
        except Exception as e:
            print(f"Failed sending email via Gmail SMTP: {e}")

    # Fallback SFR SMTP si configuré
    if not sent_success and smtp_host and smtp_user and smtp_pass:
        try:
            msg_sfr = EmailMessage(policy=email.policy.SMTPUTF8)
            msg_sfr["Subject"] = clean_subject
            msg_sfr["From"] = f"Gregory LANGLET <{smtp_user}>"
            msg_sfr["To"] = ", ".join(recipients)
            msg_sfr.set_content(html_body, subtype="html", charset="utf-8")

            print(f"Sending email to {recipients} via {smtp_host}:{smtp_port}...")
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg_sfr.as_bytes())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg_sfr.as_bytes())
            print(f"SUCCESS! Email sent via {smtp_host}.")
            sent_success = True
        except Exception as e:
            print(f"Failed sending email via {smtp_host}: {e}")

    if not sent_success:
        print("WARNING: Email could not be delivered through any SMTP provider.")

    # ── Export direct vers le Dashboard Web (Alignement 100% avec l'Email) ────
    try:
        # Récupération des scores en direct via l'API officielle LiveScore (HTTP 200)
        livescore_events = []
        try:
            today_date_str = datetime.now().strftime("%Y%m%d")
            ls_url = f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{today_date_str}/0"
            r_ls = requests.get(ls_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if r_ls.status_code == 200:
                ls_data = r_ls.json()
                for st in ls_data.get("Stages", []):
                    stage_name = (st.get("Cnm", "") + " • " + st.get("Snm", "")).strip()
                    for m_ev in st.get("Events", []):
                        eps = str(m_ev.get("Eps", ""))
                        if eps not in ["NS", "FT", "AP", "AET", "CANC", "POST", "DEFD"]:
                            h_team = m_ev.get("T1", [{}])[0].get("Nm", "")
                            a_team = m_ev.get("T2", [{}])[0].get("Nm", "")
                            h_sc = int(m_ev.get("Tr1", 0) or 0)
                            a_sc = int(m_ev.get("Tr2", 0) or 0)
                            livescore_events.append({
                                "id": str(m_ev.get("Eid", "")),
                                "home": h_team,
                                "away": a_team,
                                "score_dom": h_sc,
                                "score_ext": a_sc,
                                "minute": eps + ("'" if eps.isdigit() else ""),
                                "period_label": "En cours" if eps.isdigit() else eps,
                                "league": stage_name
                            })
            print(f"✅ LiveScore API : {len(livescore_events)} matchs en direct récupérés.")
        except Exception as e_ls:
            print(f"⚠️ Erreur sync LiveScore API : {e_ls}")

        def norm_name(name):
            return re.sub(r'\s+(FC|SC|CF|AS|AC|1\.|FK|BK|SK|IF|IK|GF|FF|VPS|Utd|United|City|Town|Club|Sporting|Real)\b', '', name or '', flags=re.IGNORECASE).strip().lower()

        def match_similarity(a, b):
            from difflib import SequenceMatcher
            return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()

        dash_matches = []
        for m in s3_matches:
            dom = m.get("dom", "")
            ext = m.get("ext", "")
            
            # Chercher si le match retenu est en direct actuellement sur LiveScore
            live_info = None
            best_sim = 0.0
            for ls in livescore_events:
                s1 = match_similarity(dom, ls["home"])
                s2 = match_similarity(ext, ls["away"])
                sim = (s1 + s2) / 2.0
                if sim > best_sim:
                    best_sim = sim
                    live_info = ls

            if live_info and best_sim >= 0.65:
                buts = live_info["score_dom"] + live_info["score_ext"]
                is_won = (buts >= 3)
                dash_matches.append({
                    "id": str(m.get("id")),
                    "dom": dom,
                    "ext": ext,
                    "league": m.get("league", live_info["league"]),
                    "start_iso": m.get("start_iso"),
                    "date_str": "En Direct",
                    "status": "LIVE",
                    "minute": live_info["minute"],
                    "period_label": live_info["period_label"],
                    "score_dom": live_info["score_dom"],
                    "score_ext": live_info["score_ext"],
                    "is_selected": True,
                    "selection_status": "WON" if is_won else "PENDING",
                    "rejection_reason": None,
                    "btts_oui": m.get("btts_oui"),
                    "btts_non": m.get("btts_non"),
                    "over25": m.get("over25"),
                    "buteur_name": m.get("buteur_name"),
                    "buteur_cote": m.get("buteur_cote"),
                    "ac_score": m.get("ac_score", 0),
                    "ac_prob": m.get("ac_prob", 0),
                    "ac_classe": m.get("ac_classe", ""),
                    "ac_red_flags": m.get("ac_red_flags", []),
                    "profit_units": round(m.get("over25", 1.0) - 1.0, 2) if is_won and m.get("over25") else 0.0
                })
            else:
                dash_matches.append({
                    "id": str(m.get("id")),
                    "dom": dom,
                    "ext": ext,
                    "league": m.get("league", "Football"),
                    "start_iso": m.get("start_iso"),
                    "date_str": m.get("date_str", "À venir"),
                    "status": "UPCOMING",
                    "score_dom": None,
                    "score_ext": None,
                    "is_selected": True,
                    "selection_status": "PENDING",
                    "rejection_reason": None,
                    "btts_oui": m.get("btts_oui"),
                    "btts_non": m.get("btts_non"),
                    "over25": m.get("over25"),
                    "buteur_name": m.get("buteur_name"),
                    "buteur_cote": m.get("buteur_cote"),
                    "ac_score": m.get("ac_score", 0),
                    "ac_prob": m.get("ac_prob", 0),
                    "ac_classe": m.get("ac_classe", ""),
                    "ac_red_flags": m.get("ac_red_flags", []),
                    "profit_units": 0.0
                })

        for m in rejected_matches:
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
                "is_selected": False,
                "selection_status": "PENDING",
                "rejection_reason": m.get("rejection_reason"),
                "btts_oui": m.get("btts_oui"),
                "btts_non": m.get("btts_non"),
                "over25": m.get("over25"),
                "buteur_name": m.get("buteur_name"),
                "buteur_cote": m.get("buteur_cote"),
                "ac_score": m.get("ac_score", 0),
                "ac_prob": m.get("ac_prob", 0),
                "ac_classe": m.get("ac_classe", ""),
                "ac_red_flags": m.get("ac_red_flags", []),
                "profit_units": 0.0
            })

        total_live_count = len([m for m in dash_matches if m["status"] == "LIVE"])


        summary = {
            "total_live": 0,
            "total_scanned_upcoming": len(scanned_results),
            "total_selected_upcoming": len(s3_matches),
            "total_history_bets": 0,
            "total_wins": 0,
            "total_losses": 0,
            "win_rate_over25": 0.0,
            "total_profit_units": 0.0,
            "roi_pct": 0.0,
            "initial_bankroll": 100.0,
            "current_bankroll": 100.0,
            "avg_odds_over25_global": avg_all_o25,
            "avg_odds_btts_global": avg_all_btts,
            "last_update": datetime.now(timezone.utc).isoformat()
        }

        serializable_combos = [
            {
                "comb_odds": c["comb_odds"],
                "stake": c["stake"],
                "gain": c["gain"],
                "profit": c["profit"],
                "match1": {
                    "dom": c["items"][0]["m"]["dom"], "ext": c["items"][0]["m"]["ext"],
                    "league": c["items"][0]["m"]["league"], "over25": c["items"][0]["m"].get("over25"), "date_str": c["items"][0]["m"]["date_str"]
                },
                "match2": {
                    "dom": c["items"][1]["m"]["dom"], "ext": c["items"][1]["m"]["ext"],
                    "league": c["items"][1]["m"]["league"], "over25": c["items"][1]["m"].get("over25"), "date_str": c["items"][1]["m"]["date_str"]
                }
            }
            for c in combos_mixed if len(c.get("items", [])) >= 2
        ]

        dash_data = {
            "summary": summary,
            "bankroll_curve": [],
            "league_stats": [],
            "tickets_2matches": serializable_combos,
            "matches": dash_matches
        }

        if os.name == "nt":  # Windows uniquement — chemin hardcodé non disponible sur GHA Linux
            dash_path = r"C:\Users\grego\Documents\DEV_DIVERS\penalty\dashboard\public\data\matches.json"
            os.makedirs(os.path.dirname(dash_path), exist_ok=True)
            with open(dash_path, "w", encoding="utf-8") as f:
                json.dump(dash_data, f, ensure_ascii=False, indent=2)
            print(f"✅ DASHBOARD JSON EXPORTÉ AVEC SUCCÈS (Alignement 100% Email) : {dash_path}")
        else:
            print("ℹ️ Export Dashboard JSON ignoré (environnement non-Windows — GHA runner)")
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

        o25_selected_ids = {m["id"] for cb in combos_mixed for m in [i["m"] for i in cb["items"]]}
        o15_selected_ids = set()
        btts_selected_ids = set()
        pen_selected_ids = {m["id"] for m in pen_simples}

        new_entries = 0
        for m in scanned_results:
            m_id = m.get("id")
            if not m_id or m_id in seen_ids:
                continue

            sels = []
            if m_id in o25_selected_ids: sels.append("O25")
            if m_id in o15_selected_ids: sels.append("O15")
            if m_id in btts_selected_ids: sels.append("BTTS")
            if m_id in pen_selected_ids: sels.append("PENALTY")

            entry = {
                "match_id": m_id,
                "timestamp_utc": now_iso,
                "match": f"{m.get('dom')} vs {m.get('ext')}",
                "league": m.get("league"),
                "date_str": m.get("date_str"),
                "scores": {
                    "o25": m.get("ac_score", 0),
                    "o15": m.get("score_o15", 0),
                    "btts": m.get("score_btts", 0),
                    "penalty": m.get("score_penalty", 0)
                },
                "referee": {
                    "name": m.get("ref_name", "Inconnu"),
                    "status": m.get("ref_status", "Arbitre non désigné — confiance réduite"),
                    "pen_per_match": m.get("pen_per_match", 0.0)
                },
                "odds": {
                    "o25": m.get("over25"),
                    "o15": m.get("over15"),
                    "btts": m.get("btts_oui")
                },
                "selected_markets": sels,
                "result": None,
                "won_o25": None,
                "won_o15": None,
                "won_btts": None,
                "won_penalty": None
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
