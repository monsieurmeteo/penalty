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

                    # Ignorer mi-temps
                    if any(x in m_desc for x in ["mi-temps", "1ère", "2ème", "quart", "période"]):
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
                "over15_real": over15 is not None,  # True = cote Unibet réelle, False = estimée
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

    # ── Sélection 100% Score AdamChoi >= 75/100 (méthode d'hier) ──
    # Seul critère : ac_score (barème composite AdamChoi) >= 75/100
    # Les Red Flags sont informatifs uniquement — ne rejettent pas.
    s3_matches = []
    rejected_matches = []

    for r in scanned_results:
        ac_score = r.get("ac_score", 0)

        if ac_score >= 75:
            r["double_confirm"] = True
            r["triple_confirm"] = True
            s3_matches.append(r)
        else:
            if ac_score > 0:
                r["rejection_reason"] = f"Score AdamChoi insuffisant ({ac_score}/100 < 75)"
            else:
                r["rejection_reason"] = "Équipe non trouvée sur AdamChoi"
            rejected_matches.append(r)

    s3_matches.sort(key=lambda x: x.get("ac_score", 0), reverse=True)

    hybrid_option_b_matches = s3_matches
    nb_triple = len(s3_matches)
    nb_double = 0
    nb_simple = 0
    print(f"⭐ Matchs validés (Score AdamChoi >= 75/100) : {len(s3_matches)} / {len(scanned_results)}")
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

    # ── Génération des Combinés : JOURNÉE + NUIT SUIVANTE = 1 BLOC
    def get_betting_session_key(m_dt, slot_only=False):
        local_dt = m_dt.astimezone(timezone(timedelta(hours=2)))
        # Si le match a lieu entre 00h00 et 05h59, il appartient à la nuit de la journée précédente
        if local_dt.hour < 6:
            betting_date = (local_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            betting_date = local_dt.strftime("%Y-%m-%d")
        slot = "nuit" if local_dt.hour < 6 else "jour"
        if slot_only:
            return slot
        return f"{betting_date}-block"

    def upgrade_sessions_to_day(sessions_dict):
        return sessions_dict

    # ── MOTEUR UNIFIÉ COMBINÉS MULTI-MARCHÉS (Bloc Journée + Nuit — Cote Min 2.00) ──
    mixed_selections = []
    
    for m in scanned_results:
        m_dt = m.get("dt_obj") or (datetime.fromisoformat(m["start_iso"].replace("Z", "+00:00")) if m.get("start_iso") else now_utc)
        block_key = get_betting_session_key(m_dt)
        
        # 1. Over 2.5 si Score >= 80
        o25 = m.get("over25")
        if m.get("ac_score", 0) >= 80 and o25:
            mixed_selections.append({
                "m": m, "id": m["id"], "dt": m_dt, "session": block_key,
                "market": "🟥 Over 2.5", "odds": o25,
                "score": m.get("ac_score", 0)
            })
        # 2. Over 1.5 si Score >= 80 (BTTS supprimé)
        elif m.get("score_o15", 0) >= 80 and m.get("freq_o15", 0.0) >= 0.65 and m.get("over15"):
            mixed_selections.append({
                "m": m, "id": m["id"], "dt": m_dt, "session": block_key,
                "market": "🟦 Over 1.5", "odds": m["over15"],
                "score": m.get("score_o15", 0)
            })

    # ── DIAGNOSTIC : breakdown des filtres ──
    n_o25 = sum(1 for m in scanned_results if m.get("ac_score", 0) >= 80 and m.get("over25"))
    n_o15 = sum(1 for m in scanned_results if m.get("score_o15", 0) >= 80 and m.get("freq_o15", 0.0) >= 0.65 and m.get("over15"))
    n_pen = sum(1 for m in scanned_results if m.get("peno_status") in ["VALIDE", "DOUBLE_SIGNAL"] and m.get("score_penalty", 0) >= 80 and m.get("ref_name", "Inconnu") not in ["", "Inconnu"])
    print(f"📊 Sélections brutes : Over2.5={n_o25} | Over1.5={n_o15} | Penalty(arbitre connu)={n_pen}")
    print(f"📊 Total sélections dans les combinés : {len(mixed_selections)}")

    # Regroupement strict par Bloc [Journée + Nuit Suivante]
    blocks_mixed = {}
    for s in mixed_selections:
        blocks_mixed.setdefault(s["session"], []).append(s)

    used_match_ids = set()
    combos_mixed = []

    # Pour chaque Bloc [Journée + Nuit], appariement chronologique des matchs (Cote Min: 2.00 STRICT)
    for b_key in sorted(blocks_mixed.keys()):
        block_items = sorted(blocks_mixed[b_key], key=lambda x: x["dt"])
        for i, s1 in enumerate(block_items):
            if s1["id"] in used_match_ids: continue

            best_partner = None
            best_diff = 999.0

            for s2 in block_items[i+1:]:
                if s2["id"] in used_match_ids or s2["id"] == s1["id"]: continue

                comb2 = round(s1["odds"] * s2["odds"], 2)
                if comb2 >= 2.15:
                    diff = abs(comb2 - 2.10)
                    if diff < best_diff:
                        best_diff = diff
                        best_partner = s2

            if best_partner:
                used_match_ids.add(s1["id"])
                used_match_ids.add(best_partner["id"])
                comb_odds = round(s1["odds"] * best_partner["odds"], 2)
                combos_mixed.append({
                    "session": b_key,
                    "type": "Doublé 2 Matchs",
                    "items": [s1, best_partner],
                    "comb_odds": comb_odds,
                    "stake": 4.0, "gain": round(4.0 * comb_odds, 2), "profit": round(4.0 * comb_odds - 4.0, 2)
                })

    # Fallback pour sélections isolées non couplées dans leur bloc (Cote Min: 2.00 STRICT)
    unpaired_selections = [s for s in mixed_selections if s["id"] not in used_match_ids]
    unpaired_selections.sort(key=lambda x: x["dt"])
    for i, s1 in enumerate(unpaired_selections):
        if s1["id"] in used_match_ids: continue
        for s2 in unpaired_selections[i+1:]:
            if s2["id"] in used_match_ids or s2["id"] == s1["id"]: continue
            comb_odds = round(s1["odds"] * s2["odds"], 2)
            if comb_odds >= 2.15:
                used_match_ids.add(s1["id"])
                used_match_ids.add(s2["id"])
                combos_mixed.append({
                    "session": f"{s1['session']}-mixte",
                    "type": "Doublé 2 Matchs",
                    "items": [s1, s2],
                    "comb_odds": comb_odds,
                    "stake": 4.0, "gain": round(4.0 * comb_odds, 2), "profit": round(4.0 * comb_odds - 4.0, 2)
                })
                break

    # ── 3b. ORPHELINS — Doublés + Triplés (Score ≥ 80, cotes réelles uniquement) ──
    # IDs des matchs déjà utilisés en penalty (ne pas les dupliquer dans les orphelins)
    pen_ids = {m["id"] for m in scanned_results
               if m.get("peno_status") in ["VALIDE", "DOUBLE_SIGNAL"]
               and m.get("score_penalty", 0) >= 80
               and m.get("ref_name", "Inconnu") not in ["", "Inconnu", None]}
    all_used = used_match_ids | pen_ids

    orphan_o25 = [s for s in mixed_selections if s["id"] not in all_used and "Over 2.5" in s["market"]]
    # Over 1.5 : uniquement cotes réelles Unibet (pas d'estimations)
    orphan_o15 = [s for s in mixed_selections if s["id"] not in all_used and "Over 1.5" in s["market"] and s["m"].get("over15_real", False)]
    orphan_o25.sort(key=lambda x: x["dt"])
    orphan_o15.sort(key=lambda x: x["dt"])

    combos_orphans = []
    used_orphan_ids = set()

    # Tier 1 — Doublés Mixte : 1× Over 2.5 + 1× Over 1.5 (cote ≥ 1.60)
    for s_o25 in orphan_o25:
        if s_o25["id"] in used_orphan_ids: continue
        teams_o25 = {s_o25["m"].get("dom","").lower(), s_o25["m"].get("ext","").lower()}
        for s_o15 in orphan_o15:
            if s_o15["id"] in used_orphan_ids or s_o15["id"] == s_o25["id"]: continue
            teams_o15 = {s_o15["m"].get("dom","").lower(), s_o15["m"].get("ext","").lower()}
            if teams_o25 & teams_o15: continue
            comb_odds = round(s_o25["odds"] * s_o15["odds"], 2)
            if comb_odds < 1.60: continue
            combos_orphans.append({"type": "Doublé Mixte", "items": [s_o25, s_o15], "comb_odds": comb_odds,
                "gain": round(4.0 * comb_odds, 2), "profit": round(4.0 * comb_odds - 4.0, 2)})
            used_orphan_ids.add(s_o25["id"])
            used_orphan_ids.add(s_o15["id"])
            break

    # Tier 2 — Triplés : 2× Over 2.5 + 1× Over 1.5 (cote ≥ 1.80)
    remaining_o25 = [s for s in orphan_o25 if s["id"] not in used_orphan_ids]
    remaining_o15 = [s for s in orphan_o15 if s["id"] not in used_orphan_ids]
    used_triplet_ids = set()
    for i, s1 in enumerate(remaining_o25):
        if s1["id"] in used_triplet_ids: continue
        for j, s2 in enumerate(remaining_o25):
            if j <= i or s2["id"] in used_triplet_ids: continue
            teams_12 = {s1["m"].get("dom","").lower(), s1["m"].get("ext","").lower(),
                        s2["m"].get("dom","").lower(), s2["m"].get("ext","").lower()}
            if len(teams_12) < 4: continue
            for s3 in remaining_o15:
                if s3["id"] in used_triplet_ids: continue
                teams_3 = {s3["m"].get("dom","").lower(), s3["m"].get("ext","").lower()}
                if teams_12 & teams_3: continue
                comb_odds = round(s1["odds"] * s2["odds"] * s3["odds"], 2)
                if comb_odds < 1.80: continue
                combos_orphans.append({"type": "Triplé 2×O2.5+O1.5", "items": [s1, s2, s3], "comb_odds": comb_odds,
                    "gain": round(4.0 * comb_odds, 2), "profit": round(4.0 * comb_odds - 4.0, 2)})
                used_triplet_ids.update([s1["id"], s2["id"], s3["id"]])
                break
            if s1["id"] in used_triplet_ids: break

    # Tier 3 — Doublés purs Over 1.5 pour orphelins restants sans partenaire O2.5 (cote ≥ 1.60)
    solo_o15 = [s for s in orphan_o15 if s["id"] not in used_orphan_ids and s["id"] not in used_triplet_ids]
    solo_o15.sort(key=lambda x: x["dt"])
    used_solo_ids = set()
    for i, s1 in enumerate(solo_o15):
        if s1["id"] in used_solo_ids: continue
        teams_1 = {s1["m"].get("dom","").lower(), s1["m"].get("ext","").lower()}
        for s2 in solo_o15[i+1:]:
            if s2["id"] in used_solo_ids: continue
            teams_2 = {s2["m"].get("dom","").lower(), s2["m"].get("ext","").lower()}
            if teams_1 & teams_2: continue
            comb_odds = round(s1["odds"] * s2["odds"], 2)
            if comb_odds < 1.60: continue
            combos_orphans.append({"type": "Doublé O1.5", "items": [s1, s2], "comb_odds": comb_odds,
                "gain": round(4.0 * comb_odds, 2), "profit": round(4.0 * comb_odds - 4.0, 2)})
            used_solo_ids.add(s1["id"])
            used_solo_ids.add(s2["id"])
            break


    # ── 4. SELECTION PENALTY OUI — PARIS SIMPLES (Validé PENO + Score ≥ 80) ──
    # Matchs validés par la compétence PENO (>= 2 pen/10m Dom & Ext) ET score_penalty >= 80
    pen_candidates = [
        m for m in scanned_results
        if m.get("peno_status") in ["VALIDE", "DOUBLE_SIGNAL"]
        and m.get("score_penalty", 0) >= 80
        and m.get("ref_name", "Inconnu") not in ["", "Inconnu", None]  # arbitre obligatoirement connu
    ]
    pen_candidates.sort(key=lambda x: (x.get("peno_status") == "DOUBLE_SIGNAL", x.get("score_penalty", 0)), reverse=True)
    pen_simples = pen_candidates

    # Matchs éliminés spécifiquement par la compétence PENO (< 2 pen/10m) pour information transparente
    pen_rejected = [
        m for m in scanned_results
        if m.get("score_penalty", 0) >= 55
        and m.get("peno_status") == "REJET"
    ]
    pen_rejected.sort(key=lambda x: x.get("score_penalty", 0), reverse=True)



    def render_match_proof_html(m, sel_score=None):
        score = sel_score if sel_score is not None else m.get("ac_score", 0)
        # Pas de données AdamChoi pour ce match → ne pas afficher de bloc vide
        if not score:
            return '<div style="color:#94a3b8; font-size:11px; font-style:italic; margin-top:6px;">📭 Données AdamChoi non disponibles pour cette équipe.</div>'
        # Recalculer le label à partir du score de sélection réel (pas toujours ac_score)
        if score >= 90:   classe = "🔥🔥🔥 Exceptionnel"
        elif score >= 85: classe = "🔥🔥 Très fort"
        elif score >= 80: classe = "🔥 Fort"
        elif score >= 75: classe = "✅ Bon potentiel"
        elif score >= 70: classe = "🟡 Intéressant"
        elif score >= 65: classe = "⚠️ Moyen"
        else:             classe = "⚠️ Fragile"
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

    # Thèmes de couleurs alternées pour les tickets combinés
    TICKET_THEMES = [
        # Thème 1: Bleu Océan
        {
            "bg_header": "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)",
            "border_card": "#93c5fd",
            "border_left": "#2563eb",
            "title_color": "#1e40af",
        },
        # Thème 2: Ambre Doré
        {
            "bg_header": "linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)",
            "border_card": "#fde68a",
            "border_left": "#d97706",
            "title_color": "#92400e",
        },
        # Thème 3: Émeraude Menthe
        {
            "bg_header": "linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)",
            "border_card": "#a7f3d0",
            "border_left": "#059669",
            "title_color": "#065f46",
        },
        # Thème 4: Violet Indigo
        {
            "bg_header": "linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)",
            "border_card": "#ddd6fe",
            "border_left": "#7c3aed",
            "title_color": "#5b21b6",
        },
        # Thème 5: Rose Ruby
        {
            "bg_header": "linear-gradient(135deg, #fff1f2 0%, #ffe4e6 100%)",
            "border_card": "#fecdd3",
            "border_left": "#e11d48",
            "title_color": "#9f1239",
        },
    ]

    combos_mixed_html = ""
    if combos_mixed:
        current_sess = None
        for idx, cb in enumerate(combos_mixed, 1):
            sess_label = cb.get("session", "")
            if sess_label != current_sess:
                current_sess = sess_label
                try:
                    dt_sess = datetime.strptime(sess_label[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    dt_sess = sess_label
                combos_mixed_html += f'<div style="font-weight:800; color:#0f172a; font-size:13px; margin:18px 0 8px 0; padding-bottom:4px; border-bottom:2px solid #3b82f6;">📅 CRENEAU [JOURNÉE DU {dt_sess} + NUIT SUIVANTE]</div>'

            theme = TICKET_THEMES[(idx - 1) % len(TICKET_THEMES)]
            items_html = ""
            for item in cb["items"]:
                m = item["m"]
                mk = item["market"]
                o = item["odds"]
                sc = item["score"]
                proof = render_match_proof_html(m, sel_score=sc)
                items_html += f'''
                <div style="margin-bottom:8px; border-bottom:1px dashed #e2e8f0; padding-bottom:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span>🔹 <b>{mk}</b> &nbsp;&bull;&nbsp; <span style="color:#0284c7; font-weight:700;">{m['date_str']}</span> &nbsp;&bull;&nbsp; <b>{m['dom']} vs {m['ext']}</b> &nbsp;&bull;&nbsp; Cote: <b>@{o:.2f}</b> <span style="color:#64748b; font-size:11px;">({m['league']})</span></span>
                        <span style="background:{'#dc2626' if sc >= 90 else '#ea580c' if sc >= 85 else '#f59e0b' if sc >= 80 else '#10b981'}; color:#fff; font-weight:800; font-size:11px; padding:2px 9px; border-radius:10px; white-space:nowrap; margin-left:8px;">⭐ {sc}/100</span>
                    </div>
                    {proof}
                </div>'''
            
            combos_mixed_html += f'''
            <div style="background:#ffffff; border:1.5px solid {theme['border_card']}; border-left:5px solid {theme['border_left']}; border-radius:10px; padding:12px 14px; margin-bottom:14px; box-shadow:0 2px 6px rgba(0,0,0,0.04);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:{theme['bg_header']}; padding:8px 10px; border-radius:6px; margin-bottom:10px; border:1px solid {theme['border_card']};">
                <span style="font-weight:800; color:{theme['title_color']}; font-size:13px;">🎟️ Ticket Multi-Marchés #{idx} ({cb['type']}) — Cote Totale: <span style="background:#ffffff; color:{theme['title_color']}; font-weight:900; padding:2px 8px; border-radius:5px; border:1px solid {theme['border_card']};">@{cb['comb_odds']:.2f}</span></span>
                <span style="font-size:12px; font-weight:700; color:#15803d; background:#dcfce7; padding:3px 9px; border-radius:6px; border:1px solid #86efac;">Mise 4,00 € &rarr; Gain Max: {cb['gain']:.2f} € (+{cb['profit']:.2f} €)</span>
              </div>
              <div style="font-size:12px; color:#334155; line-height:1.5;">
                {items_html}
              </div>
            </div>'''
    else:
        combos_mixed_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:10px;">Aucun combiné multi-marchés disponible (moins de 2 sélections éligibles).</div>'

    # ── HTML Paris Simples Penalty OUI ────────────────────────────────────────
    pen_simples_html = ""
    for idx_ps, m in enumerate(pen_simples, 1):
        ref = m.get("ref_name", "Inconnu")
        ref_status_str = m.get("ref_status") or f"👨‍⚖️ Arbitre {ref}"
        sp  = m.get("score_penalty", 0)
        avg_b = m.get("avg_booking", 0.0)
        sot_c = m.get("sot_comb", 0.0)
        sp_bg = "#dc2626" if sp >= 80 else ("#f59e0b" if sp >= 70 else "#6366f1")
        peno_b = m.get("peno_badge") or ""
        peno_badge_html = f'<div style="margin-top:3px; margin-bottom:3px;"><span style="background:#fef3c7; color:#92400e; font-weight:800; font-size:11px; padding:3px 8px; border-radius:5px; border:1px solid #fde68a;">{peno_b}</span></div>' if peno_b else ""
        pen_simples_html += f'''
        <div style="background:#faf5ff; border:1px solid #c4b5fd; border-left:4px solid #7c3aed; border-radius:8px; padding:12px 14px; margin-bottom:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-weight:900; color:#0f172a; font-size:13px;">⚡ #{idx_ps} — {m["dom"]} vs {m["ext"]}</span>
            <span style="background:{sp_bg}; color:#fff; font-weight:800; font-size:12px; padding:3px 10px; border-radius:6px;">Penalty Score: {sp}/100</span>
          </div>
          <div style="font-size:12px; color:#334155; line-height:1.9;">
            🕒 <b>{m["date_str"]}</b> &nbsp;•&nbsp; <span style="color:#64748b; font-size:11px;">{m["league"]}</span><br>
            {ref_status_str}<br>
            {peno_badge_html}
            <span style="color:#64748b; font-size:11px;">📊 Cartons H2H: {avg_b:.0f} pts &nbsp;|&nbsp; Tirs cadrés moy: {sot_c:.1f}/m</span>
          </div>
          <div style="margin-top:8px; background:#ede9fe; border-radius:5px; padding:5px 10px; font-size:11px; font-weight:700; color:#5b21b6; text-align:center;">
            🎯 PARI SIMPLE — Jouer <b>Penalty Accordé OUI</b> sur Unibet
          </div>
        </div>'''
    if not pen_simples_html:
        pen_simples_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:10px;">Aucun match Penalty OUI (arbitre non encore désigné ou score insuffisant).</div>'

    # ── HTML Matchs Éliminés par la Compétence PENO ─────────────────────────────
    pen_rejected_html = ""
    for idx_pr, m in enumerate(pen_rejected, 1):
        ref = m.get("ref_name", "Inconnu")
        ref_status_str = m.get("ref_status") or f"👨‍⚖️ Arbitre {ref}"
        sp  = m.get("score_penalty", 0)
        p_dom = m.get("p_dom_10m", 0)
        p_ext = m.get("p_ext_10m", 0)
        pen_rejected_html += f'''
        <div style="background:#fff1f2; border:1px solid #fecdd3; border-left:4px solid #e11d48; border-radius:8px; padding:10px 12px; margin-bottom:8px; opacity:0.95;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-weight:800; color:#881337; font-size:12px;">🚫 #{idx_pr} — {m["dom"]} vs {m["ext"]}</span>
            <span style="background:#ffe4e6; color:#9f1239; font-weight:700; font-size:11px; padding:2px 7px; border-radius:5px;">Score Brut: {sp}/100</span>
          </div>
          <div style="font-size:11px; color:#4c0519; line-height:1.7;">
            🕒 <b>{m["date_str"]}</b> &nbsp;•&nbsp; <span style="color:#64748b;">{m["league"]}</span> &nbsp;•&nbsp; {ref_status_str}<br>
            <span style="color:#e11d48; font-weight:800;">🛑 ÉLIMINÉ PAR LA COMPÉTENCE PENO</span> : Moins de 2 pénaltys/10m (Dom: <b>{p_dom}</b> / Ext: <b>{p_ext}</b>)
          </div>
        </div>'''
    if not pen_rejected_html:
        pen_rejected_html = '<div style="color:#94a3b8; font-style:italic; text-align:center; padding:6px; font-size:11px;">Aucun match éliminé par la compétence PENO sur ce scan.</div>'

    # ── Tableau chronologique de tous les matchs à jouer ─────────────────────
    plan_rows = []
    seen_plan = set()

    # Combinés multi-marchés
    for idx_cb, cb in enumerate(combos_mixed, 1):
        c_type = cb["type"]
        for item in cb["items"]:
            m = item["m"]
            key = (m["id"], item["market"])
            if key not in seen_plan:
                plan_rows.append({
                    "dt": item["dt"],
                    "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}",
                    "league": m.get("league", ""),
                    "market": item["market"],
                    "cote": f"@{item['odds']:.2f}",
                    "score_label": f"{item['score']}/100",
                    "score_val": item["score"],
                    "type_label": f"COMBINÉ #{idx_cb}",
                    "bg_market": "#dbeafe" if "Over 2.5" in item["market"] else ("#fef3c7" if "BTTS" in item["market"] else "#d1fae5"),
                    "cl_market": "#1e40af" if "Over 2.5" in item["market"] else ("#92400e" if "BTTS" in item["market"] else "#065f46"),
                })
                seen_plan.add(key)

    # Penalty simples
    for m in pen_simples:
        key = (m["id"], "PENALTY")
        if key not in seen_plan:
            plan_rows.append({
                "dt": m.get("dt_obj", now_utc),
                "date_str": m.get("date_str", ""),
                "match": f"{m['dom']} vs {m['ext']}",
                "league": m.get("league", ""),
                "market": "⚡ Penalty OUI",
                "cote": "SIMPLE",
                "score_label": f"{m.get('score_penalty', 0)}/100",
                "score_val": m.get("score_penalty", 0),
                "type_label": "PARI SIMPLE",
                "bg_market": "#ede9fe", "cl_market": "#5b21b6",
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
    for m in sorted(scanned_results, key=lambda x: x.get("ac_score", 0), reverse=True):
        retained = m in s3_matches
        bg_row = "#f0fdf4" if retained else "#fff"
        badge = '<span style="color:#15803d; font-weight:700;">✅ RETENU</span>' if retained else '<span style="color:#94a3b8;">—</span>'
        o25 = f"@{m['over25']:.2f}" if m.get("over25") else "N/A"
        score_v = m.get("ac_score", 0)
        btts_v = m.get("score_btts", 0)
        o15_v = m.get("score_o15", 0)
        o15_bg = "#dcfce7" if o15_v >= 75 else ("#fef3c7" if o15_v >= 50 else "#f1f5f9")
        o15_cl = "#15803d" if o15_v >= 75 else ("#92400e" if o15_v >= 50 else "#94a3b8")
        o15_badge = f'<span style="background:{o15_bg}; color:{o15_cl}; font-weight:800; font-size:11px; padding:2px 7px; border-radius:5px;">{o15_v}/100</span>' if o15_v > 0 else '<span style="color:#94a3b8;">—</span>'
        
        # Badges scores
        score_bg = "#dcfce7" if score_v >= 75 else ("#fef3c7" if score_v >= 50 else "#fee2e2")
        score_cl = "#15803d" if score_v >= 75 else ("#92400e" if score_v >= 50 else "#dc2626")
        score_badge = f'<span style="background:{score_bg}; color:{score_cl}; font-weight:800; font-size:11px; padding:2px 7px; border-radius:5px;">{score_v}/100</span>'

        btts_bg = "#dcfce7" if btts_v >= 65 else ("#fef3c7" if btts_v >= 50 else "#f1f5f9")
        btts_cl = "#15803d" if btts_v >= 65 else ("#92400e" if btts_v >= 50 else "#94a3b8")
        btts_badge = f'<span style="background:{btts_bg}; color:{btts_cl}; font-weight:800; font-size:11px; padding:2px 7px; border-radius:5px;">{btts_v}/100</span>' if btts_v > 0 else '<span style="color:#94a3b8;">—</span>'

        ref_n = m.get("ref_name", "Inconnu")
        ref_badge = f'<span style="font-size:10px; color:#475569; font-weight:600;">👨‍⚖️ {ref_n}</span>' if ref_n != "Inconnu" else '<span style="color:#94a3b8; font-size:10px;">—</span>'

        scan_rows_html += (
            f'<tr style="background:{bg_row};">'
            f'<td style="padding:7px 8px; font-size:11px; color:#475569; border-bottom:1px solid #f1f5f9;">{m.get("date_str", "")}</td>'
            f'<td style="padding:7px 8px; font-size:12px; font-weight:700; color:#0f172a; border-bottom:1px solid #f1f5f9;">{m.get("dom", "")} vs {m.get("ext", "")}'
            f'<br><span style="font-size:10px; color:#94a3b8; font-weight:400;">{m.get("league", "")}</span></td>'
            f'<td style="padding:7px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">{score_badge}</td>'
            f'<td style="padding:7px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">{o15_badge}</td>'
            f'<td style="padding:7px 6px; text-align:center; font-weight:800; font-size:12px; border-bottom:1px solid #f1f5f9;">{o25}</td>'
            f'<td style="padding:7px 6px; text-align:center; border-bottom:1px solid #f1f5f9;">{ref_badge}</td>'
            f'<td style="padding:7px 6px; text-align:center; font-size:11px; border-bottom:1px solid #f1f5f9;">{badge}</td>'
            f'</tr>'
        )

    # ── Section Duo Mixte Orphelins ──────────────────────────────────────────
    if combos_orphans:
        orphan_items_html = ""
        for idx_o, cb in enumerate(combos_orphans, 1):
            s1, s2 = cb["items"][0], cb["items"][1]
            mk1, o1, sc1 = s1["market"], s1["odds"], s1["score"]
            mk2, o2, sc2 = s2["market"], s2["odds"], s2["score"]
            m1, m2 = s1["m"], s2["m"]
            sc1_color = "#dc2626" if sc1 >= 90 else "#ea580c" if sc1 >= 85 else "#f59e0b" if sc1 >= 80 else "#10b981"
            sc2_color = "#dc2626" if sc2 >= 90 else "#ea580c" if sc2 >= 85 else "#f59e0b" if sc2 >= 80 else "#10b981"
            orphan_items_html += f"""
            <div style="background:#fff; border:1px solid #e0f2fe; border-left:4px solid #0ea5e9; border-radius:8px; padding:10px 12px; margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:800; color:#0369a1; font-size:12px;">🎟️ Duo Mixte #{idx_o} — Cote Totale: <b>@{cb['comb_odds']:.2f}</b></span>
                <span style="font-size:11px; color:#15803d; font-weight:700; background:#dcfce7; padding:2px 8px; border-radius:5px;">Mise 4€ ➔ Gain: {cb['gain']:.2f}€</span>
              </div>
              <div style="font-size:12px; color:#334155;">
                <div style="padding:4px 0; border-bottom:1px solid #f0f9ff;">
                  🔹 <b>{mk1}</b> &bull; <span style="color:#0284c7; font-weight:700;">{m1.get('date_str','')}</span> &bull; <b>{m1.get('dom','')} vs {m1.get('ext','')}</b> &bull; Cote: <b>@{o1:.2f}</b>
                  <span style="color:#64748b; font-size:10px;"> ({m1.get('league','')})</span>
                  <span style="background:{sc1_color}; color:#fff; font-weight:800; font-size:10px; padding:1px 6px; border-radius:8px; margin-left:6px;">⭐ {sc1}/100</span>
                </div>
                <div style="padding:4px 0;">
                  🔹 <b>{mk2}</b> &bull; <span style="color:#0284c7; font-weight:700;">{m2.get('date_str','')}</span> &bull; <b>{m2.get('dom','')} vs {m2.get('ext','')}</b> &bull; Cote: <b>@{o2:.2f}</b>
                  <span style="color:#64748b; font-size:10px;"> ({m2.get('league','')})</span>
                  <span style="background:{sc2_color}; color:#fff; font-weight:800; font-size:10px; padding:1px 6px; border-radius:8px; margin-left:6px;">⭐ {sc2}/100</span>
                </div>
              </div>
            </div>"""

        orphans_section_html = f"""
          <div style="padding:12px 16px 10px 16px; background:#f0f9ff; border-top:2px solid #bae6fd;">
            <div style="font-size:14px; font-weight:800; color:#0369a1; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
              <span>🔀 3. DUO MIXTE — COMBINÉS ORPHELINS (Score ≥ 80) &nbsp;<span style="font-size:11px; font-weight:600; color:#64748b;">1× Over 2.5 + 1× Over 1.5 — Sans cote minimum</span></span>
              <span style="font-size:11px; background:#bae6fd; color:#0369a1; padding:2px 8px; border-radius:6px; font-weight:700;">{len(combos_orphans)} ticket(s)</span>
            </div>
            <div style="font-size:11px; color:#0369a1; background:#e0f2fe; border-radius:5px; padding:6px 10px; margin-bottom:10px;">
              💡 Ces combinés associent <b>1 match Over 2.5 + 1 match Over 1.5</b> (Score ≥ 80/100) qui n'ont pas trouvé de partenaire à cote ≥ 2.15. Aucune équipe dupliquée.
            </div>
            {orphan_items_html}
          </div>"""
    else:
        orphans_section_html = ""

    # ── Email HTML Nouveau Design ─────────────────────────────────────────────
    now_local = datetime.now(timezone(timedelta(hours=2)))
    days_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    date_header = now_local.strftime(f"{days_fr[now_local.weekday()]} %d/%m/%Y · %Hh%M")
    nb_mixed = len(combos_mixed)
    nb_pen   = len(pen_simples)

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
            <p style="margin:7px 0 0 0; font-size:11px; color:#cbd5e1;">Analyse Multi-Marchés · Mise à jour : {now_str} · Fenêtre Journées + Nuits</p>
          </div>

          <!-- COMPTEURS -->
          <div style="background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:14px 16px;">
            <table style="width:100%; border-collapse:collapse; text-align:center;">
              <tr>
                <td style="padding:0 4px;"><div style="background:#dbeafe; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#1d4ed8;">{nb_mixed}</div><div style="font-size:10px; font-weight:700; color:#1d4ed8;">COMBINÉS</div><div style="font-size:10px; color:#3b82f6;">Cote ≥ 2.00</div></div></td>
                <td style="padding:0 4px;"><div style="background:#ede9fe; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#5b21b6;">{nb_pen}</div><div style="font-size:10px; font-weight:700; color:#5b21b6;">PENALTY OUI</div><div style="font-size:10px; color:#7c3aed;">Paris simples</div></div></td>
                <td style="padding:0 4px;"><div style="background:#f0fdf4; border-radius:8px; padding:10px;"><div style="font-size:24px; font-weight:900; color:#15803d;">{len(scanned_results)}</div><div style="font-size:10px; font-weight:700; color:#15803d;">SCANNÉS</div><div style="font-size:10px; color:#16a34a;">Jour + Nuit</div></div></td>
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

          <!-- SECTION 2 : COMBINÉS MULTI-MARCHÉS -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🚀 1. COMBINÉS MULTI-MARCHÉS CHRONOLOGIQUES &nbsp;<span style="font-size:12px; font-weight:600; color:#64748b;">(Over 2.5 • Over 1.5 — Score ≥ 80/100)</span></span>
              <span style="font-size:11px; background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:6px; font-weight:700;">{len(combos_mixed)} ticket(s)</span>
            </div>
            {combos_mixed_html}
          </div>

          <!-- SECTION 3 : PENALTY OUI PARIS SIMPLES -->
          <div style="padding:12px 16px 10px 16px; background:#faf5ff; border-top:2px solid #e2e8f0;">
            <div style="font-size:14px; font-weight:800; color:#5b21b6; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>⚡ 2. PENALTY OUI — PARIS SIMPLES</span>
              <span style="font-size:11px; background:#ede9fe; color:#5b21b6; padding:2px 8px; border-radius:6px; font-weight:700;">{len(pen_simples)} pari(s)</span>
            </div>
            <div style="font-size:11px; color:#5b21b6; background:#ede9fe; border-radius:5px; padding:6px 10px; margin-bottom:10px;">
              🚫 <b>Pas de combiné sur les penalties</b> — Chaque match = 1 pari sec <b>Penalty Accordé OUI</b> · Arbitre désigné obligatoire
            </div>
            {pen_simples_html}
          </div>

          <!-- SECTION 3b : DUO MIXTE ORPHELINS (Score >= 80, pas de cote minimum) -->
          {orphans_section_html}

          <!-- SECTION 5b : MATCHS NEUTRALISÉS PAR LA COMPÉTENCE PENO -->
          <div style="padding:12px 16px 10px 16px; background:#fff5f5; border-top:2px solid #fecdd3;">
            <div style="font-size:13px; font-weight:800; color:#9f1239; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🛡️ MATCHS NEUTRALISÉS PAR LA COMPÉTENCE PENO</span>
              <span style="font-size:11px; background:#ffe4e6; color:#9f1239; padding:2px 8px; border-radius:6px; font-weight:700;">{len(pen_rejected)} neutralisé(s)</span>
            </div>
            <div style="font-size:11px; color:#9f1239; background:#ffe4e6; border-radius:5px; padding:6px 10px; margin-bottom:10px;">
              💡 <b>Information transparente</b> : Ces matchs avaient un bon score AdamChoi (≥ 55/100) et un arbitre nommé, mais la compétence PENO vous évite de parier car au moins une équipe a &lt; 2 pénaltys sur ses 10 derniers matchs.
            </div>
            {pen_rejected_html}
          </div>

          <!-- SECTION 5 : TOUS LES MATCHS ANALYSÉS -->
          <div style="padding:12px 16px 10px 16px; background:#f8fafc; border-top:2px solid #e2e8f0;">
            <div style="font-size:13px; font-weight:800; color:#475569; margin-bottom:8px;">📊 TOUS LES MATCHS ANALYSÉS ({len(scanned_results)} scannés)</div>
            <div style="border-radius:8px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <thead><tr style="background:#f1f5f9; color:#64748b; font-size:10px; text-transform:uppercase; font-weight:700; border-bottom:1px solid #e2e8f0;">
                  <th style="padding:7px 8px; text-align:left;">Heure</th>
                  <th style="padding:7px 8px; text-align:left;">Match</th>
                  <th style="padding:7px 6px; text-align:center;">Score Over 2.5</th>
                  <th style="padding:7px 6px; text-align:center;">Score O1.5</th>
                  <th style="padding:7px 6px; text-align:center;">Cote O2.5</th>
                  <th style="padding:7px 6px; text-align:center;">Arbitre</th>
                  <th style="padding:7px 6px; text-align:center;">Statut</th>
                </tr></thead>
                <tbody>{scan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- FOOTER -->
          <div style="padding:12px 20px; background:#0f172a; font-size:10px; color:#64748b; text-align:center;">
            ⚠️ Paris sportifs · Jouez avec modération · Analyse 100% AdamChoi · Unibet France · {now_str}
          </div>

        </div>
      </body>
    </html>
    """


    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ SÉLECTION OVER 2.5 & BTTS — JOURNÉES & NUITS SUIVANTES",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}",
        f"**Critères** : BTTS OUI < BTTS NON  ET  Over 2.5 < Under 2.5\n",
        f"### 📈 Statistiques Moyennes du Marché (Unibet France)",
        f"- **Cote Over 2.5 moyenne globale (Tous matchs)** : `{avg_all_o25:.2f}` *(Matchs retenus : `{avg_sel_o25:.2f}`)*",
        f"- **Cote BTTS Oui moyenne globale (Tous matchs)** : `{avg_all_btts:.2f}` *(Matchs retenus : `{avg_sel_btts:.2f}`)*",
        f"- **Total retenus** : {len(s3_matches)} / {len(scanned_results)}\n",
        f"## 🎯 Combinés Multi-Marchés Recommandés (Cote Min: 2.00 — Mise 4,00 € / ticket)\n",
    ]

    if combos_mixed:
        for idx, cb in enumerate(combos_mixed, 1):
            report.append(f"### Ticket #{idx} ({cb['type']}) — Cote Totale: `{cb['comb_odds']:.2f}` | Mise 4.00 € → Gain Max: `{cb['gain']:.2f} €` *(+{cb['profit']:.2f} € net)*")
            for item in cb["items"]:
                m = item["m"]
                report.append(f"- **{item['market']}** : `{m['date_str']}` — **{m['dom']} vs {m['ext']}** (@`{item['odds']:.2f}`) — *{m['league']}*")
            report.append("")
    else:
        report.append("Aucun combiné multi-marchés disponible.\n")

    report.append("## ✅ Matchs Sélectionnés Individuellement")
    report.append("| Date | Ligue | Match | BTTS (Oui/Non) | Over 2.5 | Buteur Moyenne |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :--- |")
    for m in s3_matches:
        o25 = m.get("over25", "N/A")
        b_oui = m.get("btts_oui")
        b_non = m.get("btts_non")
        btts_cell = f"{b_oui:.2f} / {b_non:.2f}" if (b_oui and b_non) else (f"{b_oui:.2f}" if b_oui else "N/A")
        but = f"{m['buteur_name']} (@{m['buteur_cote']})" if m.get("buteur_name") else "N/A"
        report.append(f"| {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{btts_cell}** | **{o25}** | {but} |")

    report.append(f"\n## 🚫 Matchs Non Sélectionnés et Raisons de Rejet ({len(rejected_matches)})\n")
    report.append("| Date | Ligue | Match | BTTS (Oui/Non) | Over 2.5 | Raison du Rejet |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :--- |")
    for m in rejected_matches:
        b_oui = m.get("btts_oui")
        b_non = m.get("btts_non")
        btts_val = f"{b_oui:.2f} / {b_non:.2f}" if (b_oui and b_non) else (f"{b_oui:.2f}" if b_oui else "N/A")
        o25_val = f"{m['over25']:.2f}" if m.get("over25") is not None else "N/A"
        reason = m.get("rejection_reason", "Non éligible")
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | {btts_val} | {o25_val} | {reason} |")

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
    raw_subject = f"⚽ Football {subject_date} — {len(combos_mixed)} Combos Multi-Marchés (Cote >= 2.00) · {len(pen_simples)} Penalty OUI"
    
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
