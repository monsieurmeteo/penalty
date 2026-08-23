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
        over35, under35 = None, None
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

                    # Over / Under 2.5
                    if ("plus / moins 2.5" in m_desc or "plus / moins 2,5" in m_desc) and (over25 is None or under25 is None):
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over25 = p_val
                                elif "moins" in o_desc: under25 = p_val

                    # Over / Under 3.5
                    if ("plus / moins 3.5" in m_desc or "plus / moins 3,5" in m_desc) and (over35 is None or under35 is None):
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over35 = p_val
                                elif "moins" in o_desc: under35 = p_val

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

            margin_o25 = ((1.0/over25) + (1.0/under25)) if (over25 and under25 and over25 > 0 and under25 > 0) else 1.10
            margin_pct = round((margin_o25 - 1.0) * 100, 1) if margin_o25 else 10.0
            
            # Probabilités réelles pures SANS la marge du bookmaker ARJEL
            prob_pure_o25 = round(((1.0 / over25) / margin_o25) * 100, 1) if (over25 and margin_o25 > 0) else None
            prob_pure_u25 = round(((1.0 / under25) / margin_o25) * 100, 1) if (under25 and margin_o25 > 0) else None
            over25_fair = round(100.0 / prob_pure_o25, 2) if prob_pure_o25 else None
            under25_fair = round(100.0 / prob_pure_u25, 2) if prob_pure_u25 else None

            # Fallback estimation Under 3.5 si non listé explicitement
            if under35 is None and under25 is not None:
                under35 = round(1.0 + (under25 - 1.0) * 0.40, 2) if under25 > 1.0 else 1.20
            if over35 is None and over25 is not None:
                over35 = round(1.0 + (over25 - 1.0) * 1.75, 2) if over25 > 1.0 else 3.50

            return {
                **game,
                "dom": dom,
                "ext": ext,
                "start_iso": start_iso,
                "date_str": format_french_date(start_iso),
                "c1": c1, "cx": cx, "c2": c2,
                "over15": over15 or (round(1.0 + (over25 - 1.0) * 0.45, 2) if over25 else 1.25),
                "over25": over25, "under25": under25,
                "margin_pct": margin_pct,
                "prob_pure_o25": prob_pure_o25,
                "prob_pure_u25": prob_pure_u25,
                "over25_fair": over25_fair,
                "under25_fair": under25_fair,
                "over35": over35, "under35": under35,
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

    # Filtre Fenêtre : Matchs de Journée uniquement (08h00 - 23h59, exclusion stricte de la nuit)
    now_utc = datetime.now(timezone.utc)
    limit_36h = now_utc + timedelta(hours=36)

    scanned_results = []
    for m in scanned_all:
        start_iso = m.get("start_iso")
        if start_iso:
            try:
                m_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                m_local = m_dt.astimezone(timezone(timedelta(hours=2)))
                # Exclusion stricte de la nuit (00h00 à 07h59) -> Uniquement 08h00 à 23h59
                if 8 <= m_local.hour <= 23:
                    if (now_utc - timedelta(hours=3)) <= m_dt <= limit_36h:
                        m["dt_obj"] = m_dt
                        scanned_results.append(m)
            except Exception:
                pass

    scanned_results.sort(key=lambda x: x.get("dt_obj", now_utc))
    print(f"Matchs de Journée retenus (08h00 - 23h59) : {len(scanned_results)}")



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
                    m["score_u25"] = res.get("score_u25", 0)
                    m["score_u35"] = res.get("score_u35", 0)
                    m["prob_u25"] = res.get("prob_u25", 50.0)
                    m["prob_u35"] = res.get("prob_u35", 75.0)
                    m["freq_u25"] = res.get("freq_u25", 0.0)
                    m["freq_u35"] = res.get("freq_u35", 0.0)
                    m["risk_4plus"] = res.get("risk_4plus", 0.0)
                    m["stdev_goals"] = res.get("stdev_goals", 1.2)
                    m["pct_cs"] = res.get("pct_cs", 0.0)

                    # Calcul Edge & EV pour Under 2.5
                    u25 = m.get("under25")
                    o25 = m.get("over25")
                    if u25 and o25 and u25 > 0 and o25 > 0:
                        p_fair_u25 = (1.0 / u25) / ((1.0 / u25) + (1.0 / o25))
                        p_mod_u25 = m["prob_u25"] / 100.0
                        m["edge_u25"] = round((p_mod_u25 - p_fair_u25) * 100.0, 1)
                        m["ev_u25"] = round(((p_mod_u25 * u25) - 1.0) * 100.0, 1)

                    # Calcul Edge & EV pour Under 3.5
                    u35 = m.get("under35")
                    o35 = m.get("over35")
                    if u35 and o35 and u35 > 0 and o35 > 0:
                        p_fair_u35 = (1.0 / u35) / ((1.0 / u35) + (1.0 / o35))
                        p_mod_u35 = m["prob_u35"] / 100.0
                        m["edge_u35"] = round((p_mod_u35 - p_fair_u35) * 100.0, 1)
                        m["ev_u35"] = round(((p_mod_u35 * u35) - 1.0) * 100.0, 1)
            except Exception:
                pass
        return m


    if scanned_results and analyze_pure_stats_20:
        print(f"📊 Enrichissement AdamChoi Score /100 pour les {len(scanned_results)} matchs scannés Unibet...")
        with ThreadPoolExecutor(max_workers=10) as ex:
            scanned_results = list(ex.map(enrich_adamchoi, scanned_results))

    # ── Sélection 100% Quintuplés Over 1.5 (Seuil Score Over 1.5 >= 70/100 & Freq >= 60%) ──
    s3_matches = []
    rejected_matches = []

    for r in scanned_results:
        o25 = r.get("over25")
        u25 = r.get("under25")
        o15 = r.get("over15")
        prob_pure_o25 = r.get("prob_pure_o25") or 0.0
        score_o15 = r.get("score_o15") or 0
        freq_o15 = r.get("freq_o15") or 0.0
        
        # Validation Over 1.5 : Score Over 1.5 >= 70/100 ET Fréquence >= 60% ET Over favori Unibet
        is_score_ok = bool(score_o15 >= 70 and freq_o15 >= 60.0)
        is_val = bool(o25 and u25 and o25 < u25 and prob_pure_o25 >= 52.0 and o15 and 1.10 <= o15 <= 1.40 and is_score_ok)

        if is_val:
            r["double_confirm"] = True
            r["triple_confirm"] = True
            s3_matches.append(r)
        else:
            if o25 and u25 and o25 >= u25:
                r["rejection_reason"] = f"Under 2.5 favori (Over: @{o25:.2f} >= Under: @{u25:.2f})"
            elif score_o15 < 70:
                r["rejection_reason"] = f"Score Over 1.5 insuffisant ({score_o15}/100 < 70)"
            elif freq_o15 < 60.0:
                r["rejection_reason"] = f"Fréquence Over 1.5 trop faible ({freq_o15:.0f}% < 60%)"
            elif prob_pure_o25 < 52.0 and o25 and u25:
                r["rejection_reason"] = f"Probabilité pure sans marge trop faible ({prob_pure_o25}% < 52%)"
            elif not o25 or not u25:
                r["rejection_reason"] = "Cotes Over/Under 2.5 non disponibles sur Unibet"
            else:
                r["rejection_reason"] = f"Cote Over 1.5 hors limites (@{o15})"
            rejected_matches.append(r)

    s3_matches.sort(key=lambda x: -x.get("score_o15", 0))

    print(f"⭐ Matchs validés 100% Over 1.5 (Score >= 70/100 & Freq >= 60%) : {len(s3_matches)} / {len(scanned_results)}")




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
                "val_o15": m.get("over15"),
                "double": m.get("double_confirm", True),
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
            old_o25 = prev_s3[k].get("val_o25")
            if old_o25 and old_o25 != v["val_o25"]:
                diff = round(v["val_o25"] - old_o25, 2)
                var_s3.append({**v, "old_o25": old_o25, "diff": diff})

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
            evo_html += '<p style="color:#15803d; font-weight:bold; margin-bottom:5px;">🆕 Nouveaux matchs détectés (Over 2.5 < Under 2.5) :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in new_s3[:6]:
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>{item['match']}</b> — Over 1.5: <b>@{item.get('val_o15')}</b> (Over 2.5: @{item.get('val_o25')})</li>"
            if len(new_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(new_s3) - 6} autres nouveaux matchs</li>"
            evo_html += '</ul>'

        if var_s3:
            evo_html += '<p style="color:#1d4ed8; font-weight:bold; margin-bottom:5px;">📈 Variations de cote Over 2.5 :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_s3[:6]:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : Over 2.5 @{item['old_o25']} &rarr; <b>@{item['val_o25']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            if len(var_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(var_s3) - 6} autres variations</li>"
            evo_html += '</ul>'

        if drop_s3:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Matchs sortis de la sélection :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_s3[:6]:
                evo_html += f"<li><b>{item['match']}</b> ({item['league']})</li>"
            if len(drop_s3) > 6:
                evo_html += f"<li style='color:#94a3b8; font-style:italic;'>... et {len(drop_s3) - 6} autres matchs sortis</li>"
            evo_html += '</ul>'

        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation depuis le dernier run.</div>'

    # ── Génération des Tranches Horaires Rapprochées (Midi, Après-Midi, Soirée) ──
    def get_betting_session_key(m_dt):
        local_dt = m_dt.astimezone(timezone(timedelta(hours=2)))
        betting_date = local_dt.strftime("%Y-%m-%d")
        h = local_dt.hour
        if h < 14:
            tranche = "Matin / Midi (11h-14h)"
        elif h < 17:
            tranche = "Après-Midi (14h-17h)"
        elif h < 20:
            tranche = "Début de Soirée (17h-20h)"
        else:
            tranche = "Soirée (20h-23h59)"
        return f"{betting_date} · {tranche}"

    # ── MOTEUR UNIFIÉ OVER 1.5 (Strictement issu de s3_matches : Score >= 80/100 & Freq >= 65%) ──
    mixed_selections = []
    for m in s3_matches:
        m_dt = m.get("dt_obj") or (datetime.fromisoformat(m["start_iso"].replace("Z", "+00:00")) if m.get("start_iso") else now_utc)
        block_key = get_betting_session_key(m_dt)
        o15 = m.get("over15")
        sc_15 = m.get("score_o15", 0)

        mixed_selections.append({
            "m": m, "id": m["id"], "dt": m_dt, "session": block_key,
            "market": "⚡ Over 1.5", "odds": o15,
            "score": sc_15
        })

    # ── MOTEUR 2 : UNDER 2.5 (Désactivé en 100% Attaque) ──
    under25_selections = []

    print(f"📊 Sélections Over 1.5 (Score >= 80/100) retenues : {len(mixed_selections)}")


    # Regroupement strict par Tranche Horaire
    blocks_mixed = {}
    for s in mixed_selections:
        blocks_mixed.setdefault(s["session"], []).append(s)

    # ── MOTEUR UNIFIÉ QUINTUPLÉS OVER 1.5 (5 Matchs Chronologiques — Cote Cible ~2.40 - 3.50) ──
    used_match_ids = set()
    combos_mixed = []


    # Pour chaque Bloc, appariement chronologique des matchs 5 par 5
    for b_key in sorted(blocks_mixed.keys()):
        block_items = sorted(blocks_mixed[b_key], key=lambda x: x["dt"])
        
        available = [s for s in block_items if s["id"] not in used_match_ids]
        while len(available) >= 5:
            quint = available[:5]
            comb_odds = round(quint[0]["odds"] * quint[1]["odds"] * quint[2]["odds"] * quint[3]["odds"] * quint[4]["odds"], 2)
            for s in quint:
                used_match_ids.add(s["id"])
            combos_mixed.append({
                "session": b_key,
                "type": "Quintuplé 100% Over 1.5 (5 Matchs)",
                "items": quint,
                "comb_odds": comb_odds,
                "stake": 3.0, "gain": round(3.0 * comb_odds, 2), "profit": round(3.0 * comb_odds - 3.0, 2)
            })
            available = [s for s in block_items if s["id"] not in used_match_ids]

    # Fallback pour sélections restantes inter-blocs (5 par 5)
    unpaired = [s for s in mixed_selections if s["id"] not in used_match_ids]
    unpaired.sort(key=lambda x: x["dt"])
    while len(unpaired) >= 5:
        quint = unpaired[:5]
        comb_odds = round(quint[0]["odds"] * quint[1]["odds"] * quint[2]["odds"] * quint[3]["odds"] * quint[4]["odds"], 2)
        for s in quint:
            used_match_ids.add(s["id"])
        combos_mixed.append({
            "session": "inter-blocs",
            "type": "Quintuplé 100% Over 1.5 (5 Matchs)",
            "items": quint,
            "comb_odds": comb_odds,
            "stake": 3.0, "gain": round(3.0 * comb_odds, 2), "profit": round(3.0 * comb_odds - 3.0, 2)
        })
        unpaired = [s for s in mixed_selections if s["id"] not in used_match_ids]

    # S'il reste 4 matchs orphelins à la fin, on forme un Quadruplé
    if len(unpaired) == 4:
        quad = unpaired[:4]
        comb_odds = round(quad[0]["odds"] * quad[1]["odds"] * quad[2]["odds"] * quad[3]["odds"], 2)
        for s in quad:
            used_match_ids.add(s["id"])
        combos_mixed.append({
            "session": "cloture-mixte",
            "type": "Quadruplé 100% Over 1.5 (4 Matchs)",
            "items": quad,
            "comb_odds": comb_odds,
            "stake": 3.0, "gain": round(3.0 * comb_odds, 2), "profit": round(3.0 * comb_odds - 3.0, 2)
        })
    # S'il reste 3 matchs orphelins à la fin, on forme un Triplé
    elif len(unpaired) == 3:
        trip = unpaired[:3]
        comb_odds = round(trip[0]["odds"] * trip[1]["odds"] * trip[2]["odds"], 2)
        for s in trip: used_match_ids.add(s["id"])
        combos_mixed.append({
            "session": trip[0]["session"],
            "type": "Triplé 100% Over 1.5 (3 Matchs)",
            "items": trip, "comb_odds": comb_odds,
            "stake": 3.0, "gain": round(3.0 * comb_odds, 2), "profit": round(3.0 * comb_odds - 3.0, 2)
        })

    elif len(unpaired) == 2:
        doub = unpaired[:2]
        comb_odds = round(doub[0]["odds"] * doub[1]["odds"], 2)
        for s in doub: used_match_ids.add(s["id"])
        combos_mixed.append({
            "session": doub[0]["session"],
            "type": "Doublé 100% Over 1.5 (2 Matchs)",
            "items": doub, "comb_odds": comb_odds,
            "stake": 3.0, "gain": round(3.0 * comb_odds, 2), "profit": round(3.0 * comb_odds - 3.0, 2)
        })

    # ── MOTEUR DOUBLÉS 100% ATTAQUE (1 OVER 1.5 [Score >= 70] + 1 OVER 2.5 [Score >= 70]) ──

    second_match_selections = []
    for m in scanned_results:
        m_dt = m.get("dt_obj") or (datetime.fromisoformat(m["start_iso"].replace("Z", "+00:00")) if m.get("start_iso") else now_utc)
        block_key = get_betting_session_key(m_dt)
        o25 = m.get("over25")
        ac_score = m.get("ac_score") or 0
        
        # Seuil Score Over 2.5 >= 70/100
        if o25 and 1.65 <= o25 <= 2.35 and ac_score >= 70:
            second_match_selections.append({
                "m": m, "id": m["id"], "dt": m_dt, "session": block_key,
                "market": "🎯 Over 2.5", "odds": o25,
                "crit": f"Score {ac_score}/100", "score": ac_score
            })








    blocks_second = {}
    for s in second_match_selections:
        blocks_second.setdefault(s["session"], []).append(s)

    combos_hybrids = []
    used_doub_o15 = set()
    used_doub_sec = set()

    for b_key in sorted(blocks_second.keys()):
        sec_list = blocks_second[b_key]
        o15_list = [s for s in blocks_mixed.get(b_key, []) if s["id"] not in used_doub_o15]
        
        m_count = min(len(sec_list), len(o15_list))
        for k in range(m_count):
            it_sec = sec_list[k]
            it_o15 = o15_list[k]
            if it_sec["id"] == it_o15["id"]:
                continue
            c_odds = round(it_o15["odds"] * it_sec["odds"], 2)
            if c_odds >= 2.05:
                used_doub_sec.add(it_sec["id"])
                used_doub_o15.add(it_o15["id"])
                combos_hybrids.append({
                    "session": b_key,
                    "type": f"Doublé ({it_sec.get('market', 'Over 2.5')})",
                    "items": [it_o15, it_sec],
                    "comb_odds": c_odds,
                    "stake": 4.0, "gain": round(4.0 * c_odds, 2), "profit": round(4.0 * c_odds - 4.0, 2)
                })

    # Fallback pour matchs restants
    rem_sec = [s for s in second_match_selections if s["id"] not in used_doub_sec]
    rem_o15 = [s for s in mixed_selections if s["id"] not in used_doub_o15]

    for it_sec in rem_sec:
        avail_o15 = [s for s in rem_o15 if s["id"] != it_sec["id"]]
        if not avail_o15:
            break
        closest_o15 = min(avail_o15, key=lambda x: abs((x["dt"] - it_sec["dt"]).total_seconds()))
        c_odds = round(closest_o15["odds"] * it_sec["odds"], 2)
        if c_odds >= 2.05:
            rem_o15.remove(closest_o15)
            used_doub_sec.add(it_sec["id"])
            used_doub_o15.add(closest_o15["id"])
            combos_hybrids.append({
                "session": it_sec["session"],
                "type": f"Doublé ({it_sec.get('market', 'Over 2.5')})",
                "items": [closest_o15, it_sec],
                "comb_odds": c_odds,
                "stake": 4.0, "gain": round(4.0 * c_odds, 2), "profit": round(4.0 * c_odds - 4.0, 2)
            })





    TICKET_THEMES = [
        {"bg_header": "#eff6ff", "border_card": "#bfdbfe", "border_left": "#2563eb", "title_color": "#1e40af"},
        {"bg_header": "#fffbeb", "border_card": "#fde68a", "border_left": "#d97706", "title_color": "#92400e"},
        {"bg_header": "#ecfdf5", "border_card": "#a7f3d0", "border_left": "#059669", "title_color": "#065f46"},
        {"bg_header": "#f5f3ff", "border_card": "#ddd6fe", "border_left": "#7c3aed", "title_color": "#5b21b6"},
        {"bg_header": "#fff1f2", "border_card": "#fecdd3", "border_left": "#e11d48", "title_color": "#9f1239"},
    ]

    # Génération HTML Quintuplés Over 1.5
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
                combos_mixed_html += f'<div style="font-weight:800; color:#0f172a; font-size:12px; margin:14px 0 6px 0; padding-bottom:3px; border-bottom:2px solid #3b82f6;">📅 CRÉNEAU [{dt_sess}]</div>'

            theme = TICKET_THEMES[(idx - 1) % len(TICKET_THEMES)]
            items_rows = ""
            for item in cb["items"]:
                m = item["m"]
                o = item["odds"]
                o25 = m.get("over25", "N/A")
                u25 = m.get("under25", "N/A")
                p_pure = m.get("prob_pure_o25", 55.0)
                sc_o15 = m.get("score_o15") or m.get("ac_score") or 0
                lbl_q_badge = f"Score {sc_o15}/100" if sc_o15 >= 70 else f"{p_pure}% pure"
                
                items_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:6px 8px; font-weight:700; font-size:11px; color:#475569; white-space:nowrap;">{m['date_str']}</td>
                    <td style="padding:6px 8px; font-size:12px; font-weight:700; color:#0f172a;">{m['dom']} vs {m['ext']} <span style="font-size:10px; color:#94a3b8; font-weight:400;">({m['league']})</span></td>
                    <td style="padding:6px 8px; text-align:center;"><span style="background:#dcfce7; color:#166534; font-weight:800; font-size:11px; padding:2px 7px; border-radius:4px; white-space:nowrap;">Over 1.5 (@{o:.2f})</span></td>
                    <td style="padding:6px 8px; text-align:center; font-size:11px; color:#475569; white-space:nowrap;">O2.5: <b>@{o25}</b> &lt; U2.5: @{u25}</td>
                    <td style="padding:6px 8px; text-align:center;"><span style="background:#e0f2fe; color:#0369a1; font-weight:700; font-size:10px; padding:2px 6px; border-radius:4px; white-space:nowrap;">{lbl_q_badge}</span></td>
                </tr>'''

            
            combos_mixed_html += f'''
            <div style="background:#ffffff; border:1px solid {theme['border_card']}; border-left:4px solid {theme['border_left']}; border-radius:8px; margin-bottom:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:{theme['bg_header']}; padding:7px 10px; border-bottom:1px solid {theme['border_card']};">
                <span style="font-weight:800; color:{theme['title_color']}; font-size:12px;">🎟️ Ticket #{idx} ({cb['type']}) &bull; Cote Totale : <b style="background:#ffffff; color:{theme['title_color']}; padding:2px 7px; border-radius:4px; border:1px solid {theme['border_card']}; font-size:13px;">@{cb['comb_odds']:.2f}</b></span>
                <span style="font-size:11px; font-weight:700; color:#15803d; background:#dcfce7; padding:2px 7px; border-radius:4px;">Mise {cb['stake']:.2f} € &rarr; Gain: {cb['gain']:.2f} € (+{cb['profit']:.2f} €)</span>
              </div>
              <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <tbody>{items_rows}</tbody>
              </table>
            </div>'''
    else:
        combos_mixed_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:10px;">Aucun combiné Quintuplé disponible.</div>'

    def render_match_proof_html(m, sel_score=None):
        score = sel_score if sel_score is not None else m.get("ac_score", 0)
        if not score:
            return '<div style="color:#94a3b8; font-size:11px; font-style:italic; margin-top:6px;">📭 Données AdamChoi non disponibles pour cette équipe.</div>'
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

    # Génération HTML Doublés 100% Attaque (1 Over 1.5 + 1 Over 2.5) avec fiches complètes du 13 août
    combos_hybrids_html = ""
    if combos_hybrids:
        for idx_h, cb in enumerate(combos_hybrids, 1):
            theme = TICKET_THEMES[(idx_h - 1) % len(TICKET_THEMES)]
            items_html = ""
            for item in cb["items"]:
                m = item["m"]
                mk = item["market"]
                o = item["odds"]
                sc = item.get("score", m.get("ac_score", 0))
                proof = render_match_proof_html(m, sel_score=sc)
                items_html += f'''
                <div style="margin-bottom:8px; border-bottom:1px dashed #e2e8f0; padding-bottom:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span>🔹 <b>{mk}</b> &nbsp;&bull;&nbsp; <span style="color:#0284c7; font-weight:700;">{m['date_str']}</span> &nbsp;&bull;&nbsp; <b>{m['dom']} vs {m['ext']}</b> &nbsp;&bull;&nbsp; Cote: <b>@{o:.2f}</b> <span style="color:#64748b; font-size:11px;">({m['league']})</span></span>
                        <span style="background:{'#dc2626' if sc >= 90 else '#ea580c' if sc >= 85 else '#f59e0b' if sc >= 80 else '#10b981'}; color:#fff; font-weight:800; font-size:11px; padding:2px 9px; border-radius:10px; white-space:nowrap; margin-left:8px;">⭐ {sc}/100</span>
                    </div>
                    {proof}
                </div>'''

            combos_hybrids_html += f'''
            <div style="background:#ffffff; border:1.5px solid {theme['border_card']}; border-left:5px solid {theme['border_left']}; border-radius:10px; padding:12px 14px; margin-bottom:14px; box-shadow:0 2px 6px rgba(0,0,0,0.04);">
              <div style="display:flex; justify-content:space-between; align-items:center; background:{theme['bg_header']}; padding:8px 10px; border-radius:6px; margin-bottom:10px; border:1px solid {theme['border_card']};">
                <span style="font-weight:800; color:{theme['title_color']}; font-size:13px;">🎟️ Doublé 100% Attaque #{idx_h} ({cb['type']}) — Cote Totale: <span style="background:#ffffff; color:{theme['title_color']}; font-weight:900; padding:2px 8px; border-radius:5px; border:1px solid {theme['border_card']};">@{cb['comb_odds']:.2f}</span></span>
                <span style="font-size:12px; font-weight:700; color:#15803d; background:#dcfce7; padding:3px 9px; border-radius:6px; border:1px solid #86efac;">Mise 4,00 € &rarr; Gain Max: {cb['gain']:.2f} € (+{cb['profit']:.2f} €)</span>
              </div>
              <div style="font-size:12px; color:#334155; line-height:1.5;">
                {items_html}
              </div>
            </div>'''
    else:
        combos_hybrids_html = '<div style="color:#64748b; font-style:italic; text-align:center; padding:10px;">Aucun Doublé disponible.</div>'



    # Planning table construction
    plan_rows = []
    seen_plan = set()
    for idx_cb, cb in enumerate(combos_mixed, 1):
        for item in cb["items"]:
            m = item["m"]
            key = (m["id"], item["market"])
            if key not in seen_plan:
                p_pure = m.get("prob_pure_o25", 55.0)
                sc_o15 = m.get("score_o15") or m.get("ac_score") or 0
                lbl_q = f"Score {sc_o15}/100" if sc_o15 >= 70 else f"{p_pure}% pure"
                plan_rows.append({
                    "dt": item["dt"],
                    "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}",
                    "league": m.get("league", ""),
                    "market": item["market"],
                    "cote": f"@{item['odds']:.2f}",
                    "score_label": lbl_q,
                    "score_val": sc_o15 if sc_o15 >= 70 else int(p_pure),
                    "type_label": f"QUINTUPLÉ #{idx_cb}",
                    "bg_market": "#dcfce7",
                    "cl_market": "#166534",
                })
                seen_plan.add(key)

    for idx_h, cb in enumerate(combos_hybrids, 1):
        for item in cb["items"]:
            m = item["m"]
            key = (m["id"], item["market"])
            if key not in seen_plan:
                p_pure = m.get("prob_pure_o25", 55.0)
                ac_sc = m.get("ac_score") or 0
                
                if "1.5" in item["market"]:
                    sc_15 = m.get("score_o15") or ac_sc or 0
                    lbl_badge = f"Score {sc_15}/100" if sc_15 >= 70 else f"{p_pure}% pure"
                    score_val = sc_15 if sc_15 >= 70 else int(p_pure)
                    bg_m = "#dcfce7"
                    cl_m = "#166534"
                else:
                    lbl_badge = f"Score {ac_sc}/100" if ac_sc >= 70 else f"{p_pure}% pure"
                    score_val = ac_sc if ac_sc >= 70 else int(p_pure)
                    bg_m = "#dbeafe"
                    cl_m = "#1e40af"

                plan_rows.append({
                    "dt": item["dt"],
                    "date_str": m.get("date_str", ""),
                    "match": f"{m['dom']} vs {m['ext']}",
                    "league": m.get("league", ""),
                    "market": item["market"],
                    "cote": f"@{item['odds']:.2f}",
                    "score_label": lbl_badge,
                    "score_val": score_val,
                    "type_label": f"DOUBLÉ #{idx_h}",
                    "bg_market": bg_m,
                    "cl_market": cl_m,
                })
                seen_plan.add(key)




    plan_rows.sort(key=lambda x: x["dt"])


    # Génération HTML des lignes du planning
    plan_rows_html = ""
    for pr in plan_rows:
        plan_rows_html += (
            f'<tr>'
            f'<td style="padding:6px 8px; white-space:nowrap; font-weight:700; font-size:11px; color:#0f172a; border-bottom:1px solid #f1f5f9;">{pr["date_str"]}</td>'
            f'<td style="padding:6px 8px; border-bottom:1px solid #f1f5f9;"><b style="font-size:12px; color:#0f172a;">{pr["match"]}</b> <span style="font-size:10px; color:#94a3b8;">({pr["league"]})</span></td>'
            f'<td style="padding:6px 6px; text-align:center; border-bottom:1px solid #f1f5f9;"><span style="background:{pr["bg_market"]}; color:{pr["cl_market"]}; font-weight:700; font-size:11px; padding:2px 6px; border-radius:4px; white-space:nowrap;">{pr["market"]}</span></td>'
            f'<td style="padding:6px 6px; text-align:center; font-weight:900; font-size:12px; color:#0f172a; border-bottom:1px solid #f1f5f9;">{pr["cote"]}</td>'
            f'<td style="padding:6px 6px; text-align:center; border-bottom:1px solid #f1f5f9;"><span style="background:#e0f2fe; color:#0369a1; font-weight:700; font-size:10px; padding:2px 6px; border-radius:4px;">{pr["score_label"]}</span></td>'
            f'<td style="padding:6px 6px; text-align:center; font-size:11px; font-weight:700; color:#475569; border-bottom:1px solid #f1f5f9;">{pr["type_label"]}</td>'
            f'</tr>'
        )
    if not plan_rows_html:
        plan_rows_html = '<tr><td colspan="6" style="padding:15px; text-align:center; color:#94a3b8; font-style:italic;">Aucun match retenu sur le créneau à venir.</td></tr>'

    # ── Tableau compact des matchs analysés/rejetés ──────────────────────────
    def _sort_scan(x):
        o25 = x.get("over25")
        u25 = x.get("under25")
        o15 = x.get("over15")
        p_pure = x.get("prob_pure_o25") or 0.0
        is_fav = 1 if (o25 is not None and u25 is not None and o25 < u25 and p_pure >= 52.0) else 0
        is_tight = 1 if (o25 is not None and u25 is not None and abs(u25 - o25) <= 0.20) else 0
        o15_val = o15 if o15 is not None else 0.0
        return (is_fav or is_tight, -o15_val)

    scan_rows_html = ""
    for m in sorted(scanned_results, key=_sort_scan, reverse=True):
        o25 = m.get("over25")
        u25 = m.get("under25")
        o15 = m.get("over15")
        ac_score = m.get("ac_score") or 0
        score_o15 = m.get("score_o15") or 0
        freq_o15 = m.get("freq_o15") or 0.0
        p_pure = m.get("prob_pure_o25") if m.get("prob_pure_o25") is not None else 50.0
        diff = round(abs((u25 or 0) - (o25 or 0)), 2) if (u25 and o25) else 0.10
        is_tight = bool(u25 and o25 and diff <= 0.20)

        # 100% Attaque : Over 2.5 si Score >= 70, Over 1.5 si Score >= 70 et Freq >= 60%
        retained_o15 = bool(score_o15 >= 70 and freq_o15 >= 60.0 and o25 and u25 and o25 < u25 and p_pure >= 52.0 and o15 and 1.10 <= o15 <= 1.40)
        retained_o25 = bool(ac_score >= 70 and o25 and 1.65 <= o25 <= 2.35)
        retained = retained_o15 or retained_o25
        bg_row = "#f0fdf4" if retained else "#fff"
        
        if retained_o15 and retained_o25:
            badge = '<span style="color:#15803d; font-weight:700; font-size:10px;">✅ O1.5 + O2.5</span>'
        elif retained_o15:
            badge = '<span style="color:#15803d; font-weight:700; font-size:10px;">✅ OVER 1.5</span>'
        elif retained_o25:
            badge = '<span style="color:#2563eb; font-weight:700; font-size:10px;">🎯 OVER 2.5</span>'
        else:
            badge = '<span style="color:#94a3b8; font-size:10px;">—</span>'

        o15_txt = f"@{o15:.2f}" if o15 else "N/A"
        o25_txt = f"@{o25:.2f}" if o25 else "N/A"
        u25_txt = f"@{u25:.2f}" if u25 else "N/A"
        
        ac_tag = f" &bull; <b style='color:#d97706;'>Score {ac_score}/100</b>" if ac_score >= 70 else ""

        
        if o25 and u25 and abs(u25 - o25) <= 0.20:
            signal_txt = f'<span style="color:#2563eb; font-weight:700; font-size:10px;">Écart {abs(u25-o25):.2f} &le; 0.20{ac_tag}</span>'
        elif o25 and u25 and o25 < u25:
            signal_txt = f'<span style="color:#16a34a; font-weight:700; font-size:10px;">Over 2.5 &lt; Under ({p_pure}%){ac_tag}</span>'
        else:
            signal_txt = f'<span style="color:#94a3b8; font-size:10px;">Écart &gt; 0.20{ac_tag}</span>'






        scan_rows_html += (
            f'<tr style="background:{bg_row}; border-bottom:1px solid #f1f5f9;">'
            f'<td style="padding:5px 6px; font-size:10px; color:#475569;">{m.get("date_str", "")}</td>'
            f'<td style="padding:5px 6px; font-size:11px; font-weight:700; color:#0f172a;">{m.get("dom", "")} vs {m.get("ext", "")} <span style="font-size:9px; color:#94a3b8; font-weight:400;">({m.get("league", "")})</span></td>'
            f'<td style="padding:5px 6px; text-align:center; font-weight:800; font-size:11px; color:#16a34a;">{o15_txt}</td>'
            f'<td style="padding:5px 6px; text-align:center; font-size:10px; color:#0f172a;">{o25_txt}</td>'
            f'<td style="padding:5px 6px; text-align:center; font-size:10px; color:#64748b;">{u25_txt}</td>'
            f'<td style="padding:5px 6px; text-align:center;">{signal_txt}</td>'
            f'<td style="padding:5px 6px; text-align:center;">{badge}</td>'
            f'</tr>'
        )

    # ── Email HTML Nouveau Design Cadenas ─────────────────────────────────────
    now_local = datetime.now(timezone(timedelta(hours=2)))
    days_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    date_header = now_local.strftime(f"{days_fr[now_local.weekday()]} %d/%m/%Y · %Hh%M")
    nb_mixed = len(combos_mixed)
    nb_hybrids = len(combos_hybrids)

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
      <body style="font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif; background:#f8fafc; margin:0; padding:10px; color:#1e293b;">
        <div style="max-width:680px; margin:0 auto; background:#ffffff; border-radius:10px; overflow:hidden; border:1px solid #e2e8f0; box-shadow:0 2px 10px rgba(0,0,0,0.04);">

          <!-- HEADER COMPACT -->
          <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%); padding:16px 18px; text-align:center;">
            <div style="font-size:9px; letter-spacing:1.5px; text-transform:uppercase; color:#94a3b8; margin-bottom:4px;">⚽ FOOTBALL PREMIUM · QUINTUPLÉS OVER 1.5 & DOUBLÉS 100% ATTAQUE</div>
            <h1 style="margin:0; font-size:18px; font-weight:900; color:#ffffff;">{date_header}</h1>
            <p style="margin:4px 0 0 0; font-size:11px; color:#cbd5e1;">Quintuplés 100% Over 1.5 &bull; Doublés (1 Over 1.5 + 1 Over 2.5) &bull; Journée (08h-23h59)</p>
          </div>

          <!-- COMPTEURS COMPACTS -->
          <div style="background:#f8fafc; border-bottom:1px solid #e2e8f0; padding:8px 12px;">
            <table style="width:100%; border-collapse:collapse; text-align:center;">
              <tr>
                <td style="padding:0 3px;"><div style="background:#dbeafe; border-radius:6px; padding:6px;"><div style="font-size:18px; font-weight:900; color:#1d4ed8;">{nb_mixed}</div><div style="font-size:9px; font-weight:700; color:#1d4ed8;">QUINTUPLÉS</div><div style="font-size:9px; color:#3b82f6;">5 Over 1.5</div></div></td>
                <td style="padding:0 3px;"><div style="background:#dcfce7; border-radius:6px; padding:6px;"><div style="font-size:18px; font-weight:900; color:#15803d;">{nb_hybrids}</div><div style="font-size:9px; font-weight:700; color:#15803d;">DOUBLÉS</div><div style="font-size:9px; color:#16a34a;">Over 1.5 + Over 2.5</div></div></td>
                <td style="padding:0 3px;"><div style="background:#eff6ff; border-radius:6px; padding:6px;"><div style="font-size:18px; font-weight:900; color:#2563eb;">{len(s3_matches)}</div><div style="font-size:9px; font-weight:700; color:#2563eb;">RETENUS</div><div style="font-size:9px; color:#3b82f6;">P(Pure) ≥ 52%</div></div></td>
                <td style="padding:0 3px;"><div style="background:#f1f5f9; border-radius:6px; padding:6px;"><div style="font-size:18px; font-weight:900; color:#0f172a;">{len(scanned_results)}</div><div style="font-size:9px; font-weight:700; color:#475569;">SCANNÉS</div><div style="font-size:9px; color:#64748b;">Journée</div></div></td>
              </tr>
            </table>
          </div>

          <!-- PLANNING HEURE PAR HEURE -->
          <div style="padding:10px 14px; background:#ffffff;">
            <div style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>📅 CE QUE VOUS DEVEZ JOUER — HEURE PAR HEURE</span>
              <span style="font-size:10px; background:#eff6ff; color:#2563eb; padding:2px 6px; border-radius:4px; font-weight:700;">{len(plan_rows)} pari(s)</span>
            </div>
            <div style="border-radius:6px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <thead><tr style="background:#0f172a; color:#ffffff; font-size:9px; text-transform:uppercase; font-weight:700;">
                  <th style="padding:6px 8px; text-align:left;">Heure</th>
                  <th style="padding:6px 8px; text-align:left;">Match</th>
                  <th style="padding:6px 6px; text-align:center;">Pari</th>
                  <th style="padding:6px 6px; text-align:center;">Cote</th>
                  <th style="padding:6px 6px; text-align:center;">Critère</th>
                  <th style="padding:6px 6px; text-align:center;">Ticket</th>
                </tr></thead>
                <tbody>{plan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- EVOLUTIONS -->
          <div style="padding:0 14px 4px 14px;">{evo_html}</div>

          <!-- SECTION 2 : QUINTUPLÉS OVER 1.5 -->
          <div style="padding:10px 14px; background:#f8fafc; border-top:1px solid #e2e8f0;">
            <div style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🚀 1. QUINTUPLÉS 100% OVER 1.5 &nbsp;<span style="font-size:11px; font-weight:600; color:#64748b;">(5 Matchs · Cote Cible ~2.40 - 3.50 · Mise 3,00 €)</span></span>
              <span style="font-size:10px; background:#dbeafe; color:#1e40af; padding:2px 6px; border-radius:4px; font-weight:700;">{len(combos_mixed)} ticket(s)</span>
            </div>
            {combos_mixed_html}
          </div>

          <!-- SECTION 3 : DOUBLÉS 100% ATTAQUE (OVER 1.5 + OVER 2.5) -->
          <div style="padding:10px 14px; background:#ffffff; border-top:1px solid #e2e8f0;">
            <div style="font-size:13px; font-weight:800; color:#15803d; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
              <span>🎯 2. DOUBLÉS 100% ATTAQUE (1 OVER 1.5 + 1 OVER 2.5) &nbsp;<span style="font-size:11px; font-weight:600; color:#64748b;">(2 Matchs · Cote Cible ~2.15 - 2.60 · Mise 4,00 €)</span></span>
              <span style="font-size:10px; background:#dcfce7; color:#15803d; padding:2px 6px; border-radius:4px; font-weight:700;">{len(combos_hybrids)} ticket(s)</span>
            </div>
            {combos_hybrids_html}
          </div>




          <!-- SECTION 4 : TOUS LES MATCHS ANALYSÉS -->
          <div style="padding:10px 14px; background:#f8fafc; border-top:1px solid #e2e8f0;">
            <div style="font-size:12px; font-weight:800; color:#475569; margin-bottom:6px;">📊 AUDIT DE TOUS LES MATCHS ({len(scanned_results)} scannés)</div>
            <div style="border-radius:6px; overflow:hidden; border:1px solid #e2e8f0;">
              <table style="width:100%; border-collapse:collapse; font-size:10px;">
                <thead><tr style="background:#f1f5f9; color:#64748b; font-size:9px; text-transform:uppercase; font-weight:700; border-bottom:1px solid #e2e8f0;">
                  <th style="padding:5px 6px; text-align:left;">Heure</th>
                  <th style="padding:5px 6px; text-align:left;">Match</th>
                  <th style="padding:5px 6px; text-align:center;">Over 1.5</th>
                  <th style="padding:5px 6px; text-align:center;">Over 2.5</th>
                  <th style="padding:5px 6px; text-align:center;">Under 2.5</th>
                  <th style="padding:5px 6px; text-align:center;">Signal Match</th>
                  <th style="padding:5px 6px; text-align:center;">Statut</th>
                </tr></thead>
                <tbody>{scan_rows_html}</tbody>
              </table>
            </div>
          </div>

          <!-- FOOTER -->
          <div style="padding:10px 16px; background:#0f172a; font-size:9px; color:#64748b; text-align:center;">
            ⚽ Paris sportifs · Quintuplés Over 1.5 & Doublés Hybrides · Unibet France · {now_str}
          </div>

        </div>
      </body>
    </html>
    """



    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ SÉLECTION QUINTUPLÉS 100% OVER 1.5 — 24H JOURNÉES & NUITS SUIVANTES",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}",
        f"**Critères** : Over 2.5 < Under 2.5 & P(Pure) >= 52% (Dé-margeage ARJEL)\n",
        f"### 📈 Statistiques Moyennes du Marché (Unibet France)",
        f"- **Cote Over 2.5 moyenne globale (Tous matchs)** : `{avg_all_o25:.2f}` *(Matchs retenus : `{avg_sel_o25:.2f}`)*",
        f"- **Cote BTTS Oui moyenne globale (Tous matchs)** : `{avg_all_btts:.2f}` *(Matchs retenus : `{avg_sel_btts:.2f}`)*",
        f"- **Total retenus** : {len(s3_matches)} / {len(scanned_results)}\n",
        f"## 🎯 Quintuplés 100% Over 1.5 Recommandés (Cote Cible ~2.40 - 3.50 — Mise 3,00 € / ticket)\n",
    ]

    if combos_mixed:
        for idx, cb in enumerate(combos_mixed, 1):
            report.append(f"### Ticket #{idx} ({cb['type']}) — Cote Totale: `{cb['comb_odds']:.2f}` | Mise {cb.get('stake', 3.0):.2f} € → Gain Max: `{cb['gain']:.2f} €` *(+{cb['profit']:.2f} € net)*")
            for item in cb["items"]:
                m = item["m"]
                report.append(f"- **{item['market']}** : `{m['date_str']}` — **{m['dom']} vs {m['ext']}** (@`{item['odds']:.2f}`) — *{m['league']}*")
            report.append("")
    else:
        report.append("Aucun combiné disponible.\n")

    report.append("## ✅ Matchs Sélectionnés Individuellement")
    report.append("| Date | Ligue | Match | Over 1.5 | Over 2.5 | Under 2.5 | P(Pure) |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: | :--- |")
    for m in s3_matches:
        o15_v = f"@{m['over15']:.2f}" if m.get("over15") else "N/A"
        o25_v = f"@{m['over25']:.2f}" if m.get("over25") else "N/A"
        u25_v = f"@{m['under25']:.2f}" if m.get("under25") else "N/A"
        p_pure = m.get("prob_pure_o25", 55.0)
        report.append(f"| {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{o15_v}** | {o25_v} | {u25_v} | {p_pure}% |")

    report.append(f"\n## 🚫 Matchs Non Sélectionnés et Raisons de Rejet ({len(rejected_matches)})\n")
    report.append("| Date | Ligue | Match | Over 1.5 | Over 2.5 | Under 2.5 | Raison du Rejet |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: | :--- |")
    for m in rejected_matches:
        o15_v = f"@{m['over15']:.2f}" if m.get("over15") else "N/A"
        o25_v = f"@{m['over25']:.2f}" if m.get("over25") else "N/A"
        u25_v = f"@{m['under25']:.2f}" if m.get("under25") else "N/A"
        reason = m.get("rejection_reason", "Non éligible")
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | {o15_v} | {o25_v} | {u25_v} | {reason} |")

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
    raw_subject = f"⚽ Football {subject_date} — {len(combos_mixed)} Quintuplés Over 1.5 & {len(combos_hybrids)} Doublés Consensus"
    
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
