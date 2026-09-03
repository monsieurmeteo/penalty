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

    # ── MOTEUR DE SÉLECTIONS ET COMBINÉS 3 MATCHS (SYSTÈMES 2/3) ────────────
    # RÈGLES STRICTES :
    # 1. Same-Day : Chaque combiné est composé de 3 matchs se jouant le MÊME JOUR J (jamais de mélange jeudi/vendredi).
    # 2. Tri chronologique : Les 3 sélections de chaque ticket sont triées par heure de coup d'envoi croissante.
    # 3. Mise : 3.00 € fixe par ticket Système 2/3 (3 combinaisons x 1.00 €).
    # 4. "Ce que vous devez jouer" : Ne contient STRICTEMENT et UNIQUEMENT que les matchs présents dans ces combinés de 3 matchs.
    stake_sys = 1.00  # 1.00 € par combinaison -> 3.00 € par système 2/3

    JOURS_FR = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
    JOURS_LONGS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    def fmt_match_dt(dt_obj):
        dt_p = dt_obj.astimezone(timezone(timedelta(hours=2)))
        return f"{JOURS_FR[dt_p.weekday()]} {dt_p.strftime('%d/%m')} · {dt_p.strftime('%Hh%M')}"

    def day_label_fr(day_key):
        try:
            from datetime import date as _date
            d = _date.fromisoformat(day_key)
            return f"{JOURS_LONGS[d.weekday()]} {d.strftime('%d/%m')}"
        except Exception:
            return day_key

    def make_sys_ticket(m1, m2, m3, idx, day_k):
        """Crée un ticket Système 2/3 avec 3 matchs triés chronologiquement."""
        items = sorted([m1, m2, m3], key=lambda x: x["dt"])
        o1 = items[0]["odds"]
        o2 = items[1]["odds"]
        o3 = items[2]["odds"]
        c12 = round(o1 * o2, 2)
        c13 = round(o1 * o3, 2)
        c23 = round(o2 * o3, 2)
        min_g = round(stake_sys * min(c12, c13, c23), 2)
        max_g = round(stake_sys * (c12 + c13 + c23), 2)
        
        nb_1t = sum(1 for x in items if "1T" in x["market"])
        nb_2t = sum(1 for x in items if "2T" in x["market"])
        if nb_1t == 2 and nb_2t == 1:
            color = "#7c3aed"
            bg_hdr = "#ede9fe"
            type_desc = "Formule B (2x 1T + 1x 2T)"
        elif nb_2t == 2 and nb_1t == 1:
            color = "#2563eb"
            bg_hdr = "#dbeafe"
            type_desc = "Formule A (2x 2T + 1x 1T)"
        elif nb_2t == 3:
            color = "#0284c7"
            bg_hdr = "#e0f2fe"
            type_desc = "Sécurité 2T (3x 2ème MT)"
        else:
            color = "#d97706"
            bg_hdr = "#fef3c7"
            type_desc = "Offensif 1T (3x 1ère MT)"

        return {
            "idx": idx,
            "day": day_k,
            "items": items,
            "type_desc": type_desc,
            "color": color,
            "bg_hdr": bg_hdr,
            "c12": c12, "c13": c13, "c23": c23,
            "comb_odds": c12,
            "stake": round(stake_sys * 3, 2),
            "stake_line": stake_sys,
            "stake_tot": round(stake_sys * 3, 2),
            "gain": max_g,
            "profit": round(max_g - (stake_sys * 3), 2),
            "min_gain": min_g,
            "max_gain": max_g,
            "prof_min": round(min_g - (stake_sys * 3), 2),
            "prof_max": round(max_g - (stake_sys * 3), 2),
        }

    # Grouper les pools par jour J
    days_present = sorted(list(set([m["day"] for m in mt2_pool] + [m["day"] for m in mt1_pool])))
    all_systems = []
    sys_idx = 1

    for day_k in days_present:
        p1 = [s for s in mt1_pool if s["day"] == day_k]
        p2 = [s for s in mt2_pool if s["day"] == day_k]
        
        # Au moins 3 matchs ce jour-là pour composer des combinés
        if len(p1) + len(p2) < 3:
            continue
            
        used_day = set()

        # 1. Formule B (2x 1T + 1x 2T) sur ce jour J
        while True:
            avail_1 = [s for s in p1 if s["id"] not in used_day]
            avail_2 = [s for s in p2 if s["id"] not in used_day]
            if len(avail_1) >= 2 and len(avail_2) >= 1:
                c1, c2 = avail_1[0], avail_1[1]
                a = avail_2[0]
                used_day.update([c1["id"], c2["id"], a["id"]])
                all_systems.append(make_sys_ticket(c1, c2, a, sys_idx, day_k))
                sys_idx += 1
            else:
                break

        # 2. Formule A (2x 2T + 1x 1T) sur ce jour J
        while True:
            avail_1 = [s for s in p1 if s["id"] not in used_day]
            avail_2 = [s for s in p2 if s["id"] not in used_day]
            if len(avail_2) >= 2 and len(avail_1) >= 1:
                a1, a2 = avail_2[0], avail_2[1]
                c = avail_1[0]
                used_day.update([a1["id"], a2["id"], c["id"]])
                all_systems.append(make_sys_ticket(a1, a2, c, sys_idx, day_k))
                sys_idx += 1
            else:
                break

        # 3. Triplets 2T restants (3x 2T) sur ce jour J
        while True:
            avail_2 = [s for s in p2 if s["id"] not in used_day]
            if len(avail_2) >= 3:
                a1, a2, a3 = avail_2[0], avail_2[1], avail_2[2]
                used_day.update([a1["id"], a2["id"], a3["id"]])
                all_systems.append(make_sys_ticket(a1, a2, a3, sys_idx, day_k))
                sys_idx += 1
            else:
                break

        # 4. Triplets 1T restants (3x 1T) sur ce jour J
        while True:
            avail_1 = [s for s in p1 if s["id"] not in used_day]
            if len(avail_1) >= 3:
                c1, c2, c3 = avail_1[0], avail_1[1], avail_1[2]
                used_day.update([c1["id"], c2["id"], c3["id"]])
                all_systems.append(make_sys_ticket(c1, c2, c3, sys_idx, day_k))
                sys_idx += 1
            else:
                break

        # 5. Si 2 orphelins restent sur ce jour J, on les associe à la meilleure base du jour pour former un ticket
        left_1 = [s for s in p1 if s["id"] not in used_day]
        left_2 = [s for s in p2 if s["id"] not in used_day]
        leftovers = left_1 + left_2
        if len(leftovers) == 2 and p2:
            anchor = [s for s in p2 if s["id"] not in [x["id"] for x in leftovers]]
            if anchor:
                m1, m2 = leftovers[0], leftovers[1]
                used_day.update([m1["id"], m2["id"]])
                all_systems.append(make_sys_ticket(m1, m2, anchor[0], sys_idx, day_k))
                sys_idx += 1
        elif len(leftovers) == 1 and len(p2) >= 2:
            anchors = [s for s in p2 if s["id"] != leftovers[0]["id"]][:2]
            if len(anchors) == 2:
                used_day.add(leftovers[0]["id"])
                all_systems.append(make_sys_ticket(leftovers[0], anchors[0], anchors[1], sys_idx, day_k))
                sys_idx += 1

    print(f"🎲 Total Systèmes 2/3 générés (Same-Day) : {len(all_systems)}")

    combos_mixed = all_systems
    combos_hybrid = []
    combos_2t_pure = []
    simples_1t = []

    # ── Tableau chronologique : STRICTEMENT et UNIQUEMENT les matchs des combinés ──
    plan_rows = []
    seen_plan = set()
    for tk in all_systems:
        for item in tk["items"]:
            m = item["m"]
            key = (m["id"], item["market"])
            if key not in seen_plan:
                dt_p = item["dt"].astimezone(timezone(timedelta(hours=2)))
                jour_fr = JOURS_FR[dt_p.weekday()]
                heure_str = f"{jour_fr} {dt_p.strftime('%d/%m')} · {dt_p.strftime('%Hh%M')}"
                is_1t = "1T" in item["market"]
                plan_rows.append({
                    "dt": item["dt"],
                    "date_str": heure_str,
                    "match": f"{m['dom']} vs {m['ext']}",
                    "league": m.get("league", ""),
                    "market": item["market"],
                    "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}%",
                    "score_val": item["score"],
                    "type_label": f"SYS #{tk['idx']}",
                    "bg_market": "#fef3c7" if is_1t else "#dbeafe",
                    "cl_market": "#92400e" if is_1t else "#1e40af",
                    "id": m["id"],
                })
                seen_plan.add(key)
    plan_rows.sort(key=lambda x: x["dt"])

    # Génération HTML des lignes du planning (Design hier)
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

    # ── HTML Section Tickets Combinés 2/3 (Design coupons comme hier) ─────────
    systems_html = ""
    for day_k in days_present:
        day_systems = [tk for tk in all_systems if tk["day"] == day_k]
        if not day_systems:
            continue
            
        dt_sess = day_label_fr(day_k)
        systems_html += f'''
        <div style="font-weight:900; color:#0f172a; font-size:13px; margin:16px 0 10px 0; padding:8px 12px; background:#f1f5f9; border-left:5px solid #3b82f6; border-radius:6px;">
          📅 SESSION [JOURNÉE DU {dt_sess.upper()}] — {len(day_systems)} TICKET(S) SYSTÈME 2/3
        </div>'''
        
        for tk in day_systems:
            items_html = ""
            for item in tk["items"]:
                m = item["m"]
                dt_p = item["dt"].astimezone(timezone(timedelta(hours=2)))
                jour_fr = JOURS_FR[dt_p.weekday()]
                match_h = f"{jour_fr} {dt_p.strftime('%d/%m')} · {dt_p.strftime('%Hh%M')}"
                is_1t = "1T" in item["market"]
                
                if is_1t:
                    b_bg, b_cl, b_txt = "#fef3c7", "#92400e", f"🟡 1ère Mi-Temps la plus prolifique · {match_h}"
                    cons = "1ère Mi-Temps la plus prolifique"
                    c_border, c_bg = "#fde68a", "#fffbeb"
                    cote_cl = "#b45309"
                    sc_txt = f"Score 1T: <b>{item['score']}%</b>"
                else:
                    b_bg, b_cl, b_txt = "#dbeafe", "#1e40af", f"🔵 2ème Mi-Temps la plus prolifique · {match_h}"
                    cons = "2ème Mi-Temps la plus prolifique"
                    c_border, c_bg = "#bfdbfe", "#eff6ff"
                    cote_cl = "#1d4ed8"
                    sc_txt = f"Score 2T: <b>{item['score']}%</b>"
                    
                items_html += f'''
                <div style="background:{c_bg}; border:1px solid {c_border}; border-left:4px solid {b_cl}; padding:8px 10px; margin-bottom:6px; border-radius:6px; font-size:11px;">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">
                    <span style="font-size:10px; font-weight:700; color:{b_cl}; background:{b_bg}; padding:1px 7px; border-radius:4px;">{b_txt}</span>
                    <span style="font-size:13px; font-weight:900; color:{cote_cl}; background:#ffffff; padding:1px 7px; border-radius:4px; border:1px solid {c_border};">@{item['odds']:.2f}</span>
                  </div>
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span><b style="font-size:12px; color:#0f172a;">{m['dom']} vs {m['ext']}</b> <span style="color:#64748b; font-size:10px;">({m.get('league','')})</span></span>
                    <span style="font-size:11px; color:#475569;">{sc_txt}</span>
                  </div>
                  <div style="margin-top:2px; font-size:10px; color:{b_cl};">
                    👉 <b>Cocher sur le ticket : {cons}</b>
                  </div>
                </div>'''

            s1 = tk["items"][0]["m"]["dom"][:12]
            s2 = tk["items"][1]["m"]["dom"][:12]
            s3 = tk["items"][2]["m"]["dom"][:12]

            systems_html += f'''
            <div style="background:#ffffff; border:1.5px solid {tk['color']}44; border-left:5px solid {tk['color']}; border-radius:10px; padding:12px 14px; margin-bottom:14px; box-shadow:0 2px 6px rgba(0,0,0,0.03);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:{tk['bg_hdr']}; padding:7px 12px; border-radius:6px; margin-bottom:9px; border:1px solid {tk['color']}33;">
                <div>
                  <span style="font-weight:900; color:{tk['color']}; font-size:13px;">🎟️ SYSTÈME 2/3 #{tk['idx']} — {tk['type_desc']}</span>
                  <span style="font-size:11px; color:#64748b; font-weight:600;"> · {dt_sess}</span>
                </div>
                <div>
                  <span style="font-size:11px; font-weight:800; background:#dcfce7; color:#15803d; padding:3px 9px; border-radius:5px; border:1px solid #86efac;">
                    Mise {tk['stake_tot']:.2f} € (3 x {tk['stake_line']:.2f} €)
                  </span>
                </div>
              </div>

              <!-- 3 Sélections chronologiques -->
              <div style="margin-bottom:8px;">
                {items_html}
              </div>

              <!-- Bloc Gains & Garanties -->
              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; font-size:11px;">
                <div style="color:#475569; margin-bottom:4px;">
                  Combinaisons : Ticket 1 ({s1}+{s2}): <b>@{tk['c12']:.2f}</b> · Ticket 2 ({s1}+{s3}): <b>@{tk['c13']:.2f}</b> · Ticket 3 ({s2}+{s3}): <b>@{tk['c23']:.2f}</b>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px dashed #cbd5e1; padding-top:5px;">
                  <div style="color:#15803d; font-weight:800;">
                    🛡️ Remboursé dès 2/3 : <b>{tk['min_gain']:.2f} €</b> <span style="font-size:10px; font-weight:700;">(+{tk['prof_min']:.2f} € net)</span>
                  </div>
                  <div style="color:{tk['color']}; font-weight:900; font-size:13px;">
                    🏆 Carton plein 3/3 : <b>{tk['max_gain']:.2f} €</b> <span style="font-size:10px; font-weight:700; color:#15803d;">(+{tk['prof_max']:.2f} €)</span>
                  </div>
                </div>
              </div>
            </div>'''
            
    if not systems_html:
        systems_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:20px;">Aucun Système 2/3 disponible sur cette session.</div>'

    # ── Tableau compact des matchs analysés/rejetés ──────────────────────────
    retained_ids = set([pr["id"] for pr in plan_rows])
    scan_rows_html = ""
    for m in sorted(scanned_results, key=lambda x: x.get("ac_score", 0), reverse=True):
        retained = m["id"] in retained_ids
        bg_row = "#f0fdf4" if retained else "#fff"
        badge = '<span style="color:#15803d; font-weight:700;">✅ RETENU</span>' if retained else '<span style="color:#94a3b8;">—</span>'
        mt2_str = f"@{m['mt2_odds']:.2f}" if m.get("mt2_odds") else "N/A"
        mt1_str = f"@{m['mt1_odds']:.2f}" if m.get("mt1_odds") else "N/A"
        scan_rows_html += (
            f'<tr style="background:{bg_row}; border-bottom:1px solid #f1f5f9;">'
            f'<td style="padding:6px 8px; font-size:11px; white-space:nowrap;">{m.get("date_str", "")}</td>'
            f'<td style="padding:6px 8px;"><b style="color:#0f172a;">{m["dom"]} vs {m["ext"]}</b><br><span style="font-size:9px; color:#94a3b8;">{m.get("league", "")}</span></td>'
            f'<td style="padding:6px 4px; text-align:center; font-weight:700;">{m.get("score_2t", 0)}%</td>'
            f'<td style="padding:6px 4px; text-align:center; font-weight:700;">{m.get("score_1t", 0)}%</td>'
            f'<td style="padding:6px 4px; text-align:center;">{m.get("total_goals_brut", 0):.1f}</td>'
            f'<td style="padding:6px 4px; text-align:center; font-weight:700; color:#1d4ed8;">{mt2_str}</td>'
            f'<td style="padding:6px 4px; text-align:center; font-weight:700; color:#b45309;">{mt1_str}</td>'
            f'<td style="padding:6px 4px; text-align:center;">{badge}</td>'
            f'</tr>'
        )

    # ── Corps de l\'email (Design d\'hier avec SECTION 1 PLANNING et SECTION 2 TICKETS) ──
    tot_sys = len(all_systems)
    tot_matches_plan = len(plan_rows)
    tot_budget = tot_sys * 3.0

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
            <p style="margin:7px 0 0 0; font-size:11px; color:#cbd5e1;">Systèmes 2/3 Hybrides (1T / 2T) · Remboursé dès 2/3 · {now_str}</p>
          </div>

          <!-- COMPTEURS -->
          <div style="background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:12px 14px;">
            <table style="width:100%; border-collapse:collapse; text-align:center;">
              <tr>
                <td style="padding:0 4px;"><div style="background:#ede9fe; border-radius:8px; padding:10px 4px;"><div style="font-size:22px; font-weight:900; color:#6d28d9;">{tot_sys}</div><div style="font-size:10px; font-weight:700; color:#6d28d9;">SYSTÈMES 2/3</div><div style="font-size:9px; color:#7c3aed;">3 Matchs / ticket</div></div></td>
                <td style="padding:0 4px;"><div style="background:#dbeafe; border-radius:8px; padding:10px 4px;"><div style="font-size:22px; font-weight:900; color:#1d4ed8;">{tot_matches_plan}</div><div style="font-size:10px; font-weight:700; color:#1d4ed8;">MATCHS RETENUS</div><div style="font-size:9px; color:#3b82f6;">Dans les combinés</div></div></td>
                <td style="padding:0 4px;"><div style="background:#dcfce7; border-radius:8px; padding:10px 4px;"><div style="font-size:22px; font-weight:900; color:#15803d;">{tot_budget:.0f} €</div><div style="font-size:10px; font-weight:700; color:#15803d;">BUDGET TOTAL</div><div style="font-size:9px; color:#16a34a;">3.00 € / système</div></div></td>
                <td style="padding:0 4px;"><div style="background:#fef3c7; border-radius:8px; padding:10px 4px;"><div style="font-size:22px; font-weight:900; color:#b45309;">DÈS 2/3</div><div style="font-size:10px; font-weight:700; color:#b45309;">GARANTIE</div><div style="font-size:9px; color:#d97706;">Remboursé ou gagnant</div></div></td>
              </tr>
            </table>
          </div>

          <!-- SECTION 1 : PLANNING HEURE PAR HEURE (Design hier) -->
          <div style="padding:16px 16px 8px 16px;">
            <div style="font-size:14px; font-weight:900; color:#0f172a; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
              <span>📅 CE QUE VOUS DEVEZ JOUER — HEURE PAR HEURE</span>
              <span style="font-size:11px; background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:6px;">{len(plan_rows)} match(s)</span>
            </div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <thead><tr style="background:#0f172a; color:#ffffff; font-size:10px; text-transform:uppercase; font-weight:700;">
                  <th style="padding:9px 8px; text-align:left; white-space:nowrap;">Heure</th>
                  <th style="padding:9px 8px; text-align:left;">Match</th>
                  <th style="padding:9px 6px; text-align:center; min-width:100px;">Marché</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Cote</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Score</th>
                  <th style="padding:9px 6px; text-align:center; white-space:nowrap;">Système</th>
                </tr></thead>
                <tbody>{plan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- EVOLUTIONS -->
          <div style="padding:0 16px 8px 16px;">{evo_html}</div>

          <!-- SECTION 2 : LES TICKETS COMBINÉS 2/3 (Design hier) -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🎟️ SYSTÈMES MULTIPLES 2/3 (3 MATCHS PAR TICKET) &nbsp;<span style="font-size:12px; font-weight:600; color:#64748b;">(Mise 3.00 € · Remboursé dès 2/3)</span></span>
              <span style="font-size:11px; background:#ede9fe; color:#6d28d9; padding:2px 8px; border-radius:6px; font-weight:700;">{len(all_systems)} ticket(s)</span>
            </div>
            {systems_html}
          </div>

          <!-- SECTION 3 : TOUS LES MATCHS ANALYSÉS -->
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
        f"# ⚽ SÉLECTION SYSTÈMES 2/3 HYBRIDES — MISE 3.00 €",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}",
        f"**Matchs Retenus dans les Combinés** : {len(plan_rows)}",
        f"**Systèmes 2/3 Générés** : {len(all_systems)} tickets (Mise 3.00 € par ticket, remboursé dès 2/3)\n",
        f"## 📅 CE QUE VOUS DEVEZ JOUER — HEURE PAR HEURE\n",
        f"| Heure | Match | Ligue | Marché | Cote | Score | Système |",
        f"|:---:|:---|:---|:---:|:---:|:---:|:---:|",
    ]
    for pr in plan_rows:
        report.append(f"| {pr['date_str']} | **{pr['match']}** | {pr['league']} | {pr['market']} | {pr['cote']} | {pr['score_label']} | {pr['type_label']} |")

    report.append("\n## 🎟️ DÉTAIL DES TICKETS SYSTÈMES 2/3\n")
    for tk in all_systems:
        report.append(f"### Système 2/3 #{tk['idx']} — {tk['type_desc']} ({day_label_fr(tk['day'])})")
        report.append(f"- **Mise** : 3.00 € (3 x 1.00 €)")
        for it in tk["items"]:
            m = it["m"]
            report.append(f"  - {it['market']} : **{m['dom']} vs {m['ext']}** (@`{it['odds']:.2f}`) — Score: {it['score']}%")
        report.append(f"- **Combinaisons** : {tk['items'][0]['m']['dom'][:10]}+{tk['items'][1]['m']['dom'][:10]} (@`{tk['c12']:.2f}`) | {tk['items'][0]['m']['dom'][:10]}+{tk['items'][2]['m']['dom'][:10]} (@`{tk['c13']:.2f}`) | {tk['items'][1]['m']['dom'][:10]}+{tk['items'][2]['m']['dom'][:10]} (@`{tk['c23']:.2f}`)")
        report.append(f"- **Gains** : Remboursé dès 2/3 : `{tk['min_gain']:.2f} €` *(+{tk['prof_min']:.2f} € net)* | Carton plein 3/3 : `{tk['max_gain']:.2f} €` *(+{tk['prof_max']:.2f} € net)*\n")

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
    raw_subject = f"⚽ Football {subject_date} — {len(all_systems)} Systèmes 2/3 (Mise 3€) · {len(plan_rows)} Matchs à Jouer"
    
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
