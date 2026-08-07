import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "japon", "coree-du-sud", "australie", "coupes-d-europe", "international"
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

    games = []
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
                games.append({
                    "id": parts[-2],
                    "dom": dom_name,
                    "ext": ext_name,
                    "league": league_name,
                    "url": url,
                    "timestamp": int(time.time()),
                    "start_time": "À venir"
                })

    print(f"Fixtures trouvées : {len(games)}")
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

        c1 = cx = c2 = over25 = under25 = s22 = btts_oui = None
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

                    # Over 2.5
                    if ("plus / moins 2.5" in m_desc or "plus / moins 2,5" in m_desc) and over25 is None:
                        if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "plus" in o_desc: over25 = p_val
                                elif "moins" in o_desc: under25 = p_val

                    # Score exact 2-2
                    if "score exact" in m_desc and s22 is None:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if o_desc in ["2 - 2", "2-2"]: s22 = p_val

                    # BTTS Oui (Les 2 équipes marquent)
                    if m_desc in ["les 2 équipes marqueront-elles ?", "les 2 équipes marqueront-elles", "deux équipes marqueront-elles ?", "deux équipes marqueront-elles"] and btts_oui is None:
                        for o in outcomes:
                            o_desc = (o.get("description") or "").strip().lower()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                            if o_desc == "oui": btts_oui = p_val
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
                            p_name = (o.get("description") or "").strip()
                            p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
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
                "over25": over25, "under25": under25, "over25_fair": over25_fair,
                "s22": s22,
                "btts_oui": btts_oui,
                "buteur_name": buteur_name,
                "buteur_cote": buteur_cote,
                "buteur_avg": buteur_avg,
            }
    except Exception:
        return None
    return None

def main():
    print("=== AUTOMATISATION UNIBET — MÉTHODE YOUTUBE OVER 2.5 (48H) ===")
    matches_to_scan = get_unibet_active_games()

    scanned_all = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_all.append(res)

    # Filtre 48h
    now_utc = datetime.now(timezone.utc)
    limit_48h = now_utc + timedelta(hours=48)

    scanned_results = []
    for m in scanned_all:
        start_iso = m.get("start_iso")
        if start_iso:
            try:
                m_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                if now_utc <= m_dt <= limit_48h:
                    m["dt_obj"] = m_dt
                    scanned_results.append(m)
            except Exception:
                scanned_results.append(m)
        else:
            scanned_results.append(m)

    scanned_results.sort(key=lambda x: x.get("dt_obj", now_utc))
    print(f"Matchs dans la fenêtre 48h : {len(scanned_results)}")

    # ── Sélection Stricte : Score 2-2 ≤ 12.00 ET 1.55 ≤ Over 2.5 ≤ 1.70 ───────
    s3_matches = []
    rejected_matches = []

    for r in scanned_results:
        s22 = r.get("s22")
        o25 = r.get("over25")

        reasons = []
        if s22 is None:
            reasons.append("Score 2-2 non disponible")
        elif s22 > SEUIL_S3:
            reasons.append(f"Score 2-2 = {s22:.2f} (> {SEUIL_S3:.2f})")

        if o25 is None:
            reasons.append("Over 2.5 non disponible")
        elif o25 < MIN_COTE_O25:
            reasons.append(f"Over 2.5 = {o25:.2f} (< {MIN_COTE_O25:.2f})")
        elif o25 > MAX_COTE_O25:
            reasons.append(f"Over 2.5 = {o25:.2f} (> {MAX_COTE_O25:.2f})")

        if not reasons:
            r["double_confirm"] = True
            r["triple_confirm"] = True
            s3_matches.append(r)
        else:
            r["rejection_reason"] = " • ".join(reasons)
            rejected_matches.append(r)

    s3_matches.sort(key=lambda x: x.get("dt_obj", now_utc))
    rejected_matches.sort(key=lambda x: x.get("dt_obj", now_utc))

    nb_triple = len(s3_matches)
    nb_double = 0
    nb_simple = 0
    print(f"Matchs retenus (Score 2-2 ≤ {SEUIL_S3} & Over 2.5 [{MIN_COTE_O25}-{MAX_COTE_O25}]) : {len(s3_matches)}")
    print(f"Matchs rejetés : {len(rejected_matches)}")

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
                "val_s22": m["s22"],
                "val_o25": m.get("over25"),
                "double": m["double_confirm"],
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
            old_s22 = prev_s3[k].get("val_s22")
            if old_s22 and old_s22 != v["val_s22"]:
                diff = round(v["val_s22"] - old_s22, 2)
                var_s3.append({**v, "old_s22": old_s22, "diff": diff})

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
            for item in new_s3:
                badge = " ⭐⭐ DOUBLE" if item.get("double") else ""
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>{item['match']}</b> — 2-2: <b>{item['val_s22']}</b>{badge}</li>"
            evo_html += '</ul>'

        if var_s3:
            evo_html += '<p style="color:#1d4ed8; font-weight:bold; margin-bottom:5px;">📈 Variations de cote Score 2-2 :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_s3:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : Score 2-2 {item['old_s22']} &rarr; <b>{item['val_s22']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            evo_html += '</ul>'

        if drop_s3:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Matchs sortis de la sélection :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_s3:
                evo_html += f"<li><b>{item['match']}</b> ({item['league']})</li>"
            evo_html += '</ul>'

        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation depuis le dernier run.</div>'

    # ── Génération des cartes de matchs ──────────────────────────────────────
    yt_cards = ""
    # ── Pré-construction du tableau des matchs validés ─────────────────────
    table_rows_html = ""
    for idx, m in enumerate(s3_matches):
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        s22 = m.get("s22", "N/A")
        o25 = m.get("over25", "N/A")
        if m.get("buteur_name"):
            buteur_cell = f'<b>{m["buteur_name"]}</b> (@{m["buteur_cote"]})'
        else:
            buteur_cell = '<span style="color:#94a3b8; font-style:italic;">N/A</span>'

        table_rows_html += (
            f'<tr style="background:{bg}; border-bottom:1px solid #e2e8f0;">'
            f'<td style="padding:10px 10px; color:#475569; white-space:nowrap; font-size:12px;">{m["date_str"]}</td>'
            f'<td style="padding:10px 10px; font-weight:700; color:#0f172a;">{m["dom"]} vs {m["ext"]}'
            f'<br><span style="font-size:11px; color:#64748b; font-weight:400;">{m["league"]}</span></td>'
            f'<td style="padding:10px 10px; text-align:center;"><span style="background:#fffbeb; color:#b45309; border:1px solid #fef08a; padding:3px 8px; border-radius:6px; font-weight:800; font-size:12px;">{s22}</span></td>'
            f'<td style="padding:10px 10px; text-align:center;"><span style="background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; padding:3px 8px; border-radius:6px; font-weight:800; font-size:12px;">{o25}</span></td>'
            f'<td style="padding:10px 10px; text-align:left; color:#1e293b; font-size:12px;">{buteur_cell}</td>'
            f'</tr>'
        )

    if not table_rows_html:
        table_rows_html = f'''
        <tr>
          <td colspan="5" style="padding:24px; text-align:center; color:#64748b; font-style:italic;">
            Aucun match ne valide les critères stricts (Score 2-2 &le; {SEUIL_S3} et Over 2.5 entre {MIN_COTE_O25} et {MAX_COTE_O25}) dans les prochaines 48h.
          </td>
        </tr>
        '''

    # ── Pré-construction du tableau des matchs NON retenus & motifs ────────
    rejected_rows_html = ""
    for idx, m in enumerate(rejected_matches):
        bg = "#ffffff" if idx % 2 == 0 else "#f9fafb"
        s22_val = f"{m['s22']:.2f}" if m.get("s22") is not None else '<span style="color:#94a3b8;">N/A</span>'
        o25_val = f"{m['over25']:.2f}" if m.get("over25") is not None else '<span style="color:#94a3b8;">N/A</span>'
        reason = m.get("rejection_reason", "Non éligible")

        rejected_rows_html += (
            f'<tr style="background:{bg}; border-bottom:1px solid #e5e7eb;">'
            f'<td style="padding:7px 8px; color:#6b7280; white-space:nowrap; font-size:11px;">{m["date_str"]}</td>'
            f'<td style="padding:7px 8px; font-weight:600; color:#374151; font-size:12px;">{m["dom"]} vs {m["ext"]}'
            f'<br><span style="font-size:10px; color:#9ca3af;">{m["league"]}</span></td>'
            f'<td style="padding:7px 8px; text-align:center; font-size:11px; font-weight:600;">{s22_val}</td>'
            f'<td style="padding:7px 8px; text-align:center; font-size:11px; font-weight:600;">{o25_val}</td>'
            f'<td style="padding:7px 8px; text-align:left; color:#dc2626; font-size:11px; font-weight:600;">{reason}</td>'
            f'</tr>'
        )

    if not rejected_rows_html:
        rejected_rows_html = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#94a3b8; font-style:italic;">Aucun match scanné n\'a été rejeté.</td></tr>'

    # ── Corps du mail HTML Épuré, Compact & Moderne ──────────────────────────
    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
      </head>
      <body style="font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin:0; padding: 15px; color:#1e293b;">
        <div style="max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.04);">

          <!-- BANNIÈRE HEADER -->
          <div style="background: #0f172a; padding: 20px; text-align: center; color: white;">
            <h1 style="margin: 0; font-size: 20px; font-weight: 800; letter-spacing: 0.5px; color: #ffffff;">⚽ OVER 2.5 & BTTS — SÉLECTION UNIBET</h1>
            <p style="margin: 6px 0 0 0; font-size: 13px; color: #94a3b8;">Score 2-2 ≤ {SEUIL_S3} &nbsp;•&nbsp; Cote Over 2.5 [{MIN_COTE_O25} – {MAX_COTE_O25}]</p>
            <div style="margin-top: 10px; display: inline-block; background: rgba(255,255,255,0.12); padding: 3px 12px; border-radius: 15px; font-size: 11px; color: #cbd5e1;">
              Mise à jour : {now_str}
            </div>
          </div>

          <!-- SYNTHÈSE COMPACTE -->
          <div style="padding: 12px 20px; background: #f1f5f9; border-bottom: 1px solid #e2e8f0; font-size: 13px; font-weight: 700; color: #0f172a; display:flex; justify-content:space-between; align-items:center;">
            <span>🔥 <b>{len(s3_matches)} match(s) retenu(s)</b> sur {len(scanned_results)} scannés</span>
            <span style="font-size:11px; color:#64748b; font-weight:normal;">Fenêtre 48h</span>
          </div>

          <!-- TABLEAU UNIQUE COMPACT DES MATCHS SELECTIONNÉS -->
          <div style="padding: 10px;">
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
              <thead>
                <tr style="background:#f8fafc; color:#475569; text-transform:uppercase; font-size:11px; font-weight:700; border-bottom:2px solid #e2e8f0;">
                  <th style="padding:9px 10px; text-align:left;">Date</th>
                  <th style="padding:9px 10px; text-align:left;">Match & Ligue</th>
                  <th style="padding:9px 10px; text-align:center;">Score 2-2</th>
                  <th style="padding:9px 10px; text-align:center;">Over 2.5</th>
                  <th style="padding:9px 10px; text-align:left;">Buteur Moyenne</th>
                </tr>
              </thead>
              <tbody>
                {table_rows_html}
              </tbody>
            </table>
          </div>

          <!-- SECTION MATCHS NON SÉLECTIONNÉS ET MOTIFS DE REJET -->
          <div style="padding: 15px 10px; border-top: 2px solid #e2e8f0; background: #fafafa;">
            <div style="font-size: 13px; font-weight: 800; color: #475569; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;">
              <span>🚫 MATCHS NON SÉLECTIONNÉS ({len(rejected_matches)}) & RAISONS DU REJET</span>
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:12px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; overflow:hidden;">
              <thead>
                <tr style="background:#f1f5f9; color:#475569; text-transform:uppercase; font-size:10px; font-weight:700; border-bottom:1px solid #cbd5e1;">
                  <th style="padding:8px 10px; text-align:left;">Date</th>
                  <th style="padding:8px 10px; text-align:left;">Match & Ligue</th>
                  <th style="padding:8px 10px; text-align:center;">Score 2-2</th>
                  <th style="padding:8px 10px; text-align:center;">Over 2.5</th>
                  <th style="padding:8px 10px; text-align:left;">Raison du Rejet</th>
                </tr>
              </thead>
              <tbody>
                {rejected_rows_html}
              </tbody>
            </table>
          </div>

          <!-- FOOTER -->
          <div style="padding: 12px 20px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; text-align: center;">
            ⚠️ Paris sportifs à l'unité · Analyse basée sur cotes Unibet France · Jouez avec modération.
          </div>

        </div>
      </body>
    </html>
    """

    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ SÉLECTION STRICTE OVER 2.5 — UNIBET 48H",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}",
        f"**Critères** : Score 2-2 ≤ {SEUIL_S3}  |  Cote Over 2.5 [{MIN_COTE_O25} – {MAX_COTE_O25}]\n",
        f"**Total retenus** : {len(s3_matches)}\n",
        "## ✅ Matchs Sélectionnés",
        "| Date | Ligue | Match | Score 2-2 | Over 2.5 | Buteur Moyenne |",
        "| :---: | :--- | :--- | :---: | :---: | :--- |",
    ]
    for m in s3_matches:
        o25 = m.get("over25", "N/A")
        but = f"{m['buteur_name']} (@{m['buteur_cote']})" if m.get("buteur_name") else "N/A"
        report.append(f"| {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{m['s22']}** | **{o25}** | {but} |")

    report.append(f"\n## 🚫 Matchs Non Sélectionnés et Raisons de Rejet ({len(rejected_matches)})\n")
    report.append("| Date | Ligue | Match | Score 2-2 | Over 2.5 | Raison du Rejet |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :--- |")
    for m in rejected_matches:
        s22_val = f"{m['s22']:.2f}" if m.get("s22") is not None else "N/A"
        o25_val = f"{m['over25']:.2f}" if m.get("over25") is not None else "N/A"
        reason = m.get("rejection_reason", "Non éligible")
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | {s22_val} | {o25_val} | {reason} |")

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
    subject_flag = f"{nb_s3} match{'s' if nb_s3>1 else ''} retenu{'s' if nb_s3>1 else ''} (2-2 ≤ 12.00 & O2.5 [1.55-1.70])"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Rapport foot du {subject_date} - {subject_flag}"
    msg["From"]    = f"Gregory LANGLET <{smtp_user if smtp_user else gmail_email}>"
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    sent_success = False

    # Option A: SFR / Custom SMTP
    if smtp_host and smtp_user and smtp_pass:
        try:
            print(f"Sending email to {recipients} via {smtp_host}:{smtp_port}...")
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, recipients, msg.as_string())
            print(f"SUCCESS! Email sent via {smtp_host}.")
            sent_success = True
        except Exception as e:
            print(f"Failed sending email via {smtp_host}: {e}")

    # Option B: Gmail SMTP (en secours ou en complément)
    if not sent_success and gmail_password:
        try:
            print(f"Sending email to {recipients} via Gmail SMTP...")
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

    if not sent_success:
        print("WARNING: Email could not be delivered through any SMTP provider.")

if __name__ == "__main__":
    main()
