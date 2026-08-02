import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SEUIL_S8 = 2.90
SEUIL_S4 = 1.87

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
    print(f"Deep scraping Unibet France football catalog across all {len(COUNTRIES)} country categories...")
    
    all_match_urls = set()
    
    def fetch_country(c):
        url = f"https://www.unibet.fr/paris-football/{c}"
        urls_found = set()
        try:
            r = requests.get(url, headers=H, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if "/paris-football/" in href and "vs" in href and len(href.split("/")) >= 5:
                        full_url = f"https://www.unibet.fr{href}" if href.startswith("/") else href
                        urls_found.add(full_url)
        except Exception:
            pass
        return urls_found

    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = [ex.submit(fetch_country, c) for c in COUNTRIES]
        for f in as_completed(futs):
            all_match_urls.update(f.result())
            
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
                league_name = parts[1].replace("-", " ").title() + " " + parts[2].replace("-", " ").title()
                games.append({
                    "id": parts[-2],
                    "dom": dom_name,
                    "ext": ext_name,
                    "league": league_name,
                    "url": url,
                    "timestamp": int(time.time()),
                    "start_time": "À venir"
                })
                
    print(f"Extracted {len(games)} total active football fixtures across all countries on Unibet France.")
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
            
        c1 = cx = c2 = over25 = under25 = s22 = pen_oui = pen_non = pen_eq1 = pen_eq2 = None
        start_iso = ""
        
        for js in json_scripts:
            content = js.string or ""
            if "EventsDetail" in content:
                data = json.loads(content)
                events = data.get("EventsDetail", {}).get("events", [])
                if not events: continue
                event = events[0]
                
                dom = event.get("opponentA", {}).get("label") or game["dom"]
                ext = event.get("opponentB", {}).get("label") or game["ext"]
                start_iso = event.get("parsedStart") or ""
                
                grouped_markets = event.get("groupedMarkets", [])
                for g in grouped_markets:
                    markets = g.get("markets", [])
                    for m in markets:
                        m_desc = (m.get("description") or "").lower()
                        
                        if any(x in m_desc for x in ["mi-temps", "1ère", "2ème", "quart", "période"]):
                            continue
                            
                        outcomes = m.get("outcomes", [])
                        
                        if m_desc in ["1 n 2", "1n2", "résultat du match"] and c1 is None:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if dom.lower() in o_desc or "1" in o_desc: c1 = p_val
                                elif ext.lower() in o_desc or "2" in o_desc: c2 = p_val
                                elif "nul" in o_desc: cx = p_val
                                
                        if ("plus / moins 2.5" in m_desc or "plus / moins 2,5" in m_desc) and over25 is None:
                            if not any(t in m_desc for t in [dom.lower(), ext.lower(), "équipe"]):
                                for o in outcomes:
                                    o_desc = (o.get("description") or "").lower()
                                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                    if "plus" in o_desc: over25 = p_val
                                    elif "moins" in o_desc: under25 = p_val
                                    
                        if "penalty" in m_desc:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "une des 2" in o_desc or "une des deux" in o_desc: pen_oui = p_val
                                elif "pas de penalty" in o_desc: pen_non = p_val
                                elif "equipe 1" in o_desc or "équipe 1" in o_desc: pen_eq1 = p_val
                                elif "equipe 2" in o_desc or "équipe 2" in o_desc: pen_eq2 = p_val
                                
                        if "score exact" in m_desc and s22 is None:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").strip()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if o_desc in ["2 - 2", "2-2"]: s22 = p_val
                                    
                margin_o25 = ((1.0/over25) + (1.0/under25)) if (over25 and under25 and over25 > 0 and under25 > 0) else 1.12
                over25_fair = round(over25 * margin_o25, 2) if over25 else None
                
                margin_pen = ((1.0/pen_oui) + (1.0/pen_non)) if (pen_oui and pen_non and pen_oui > 0 and pen_non > 0) else 1.15
                pen_oui_fair = round(pen_oui * margin_pen, 2) if pen_oui else None
                
                return {
                    **game,
                    "dom": dom,
                    "ext": ext,
                    "start_iso": start_iso,
                    "date_str": format_french_date(start_iso),
                    "c1": c1, "cx": cx, "c2": c2,
                    "over25": over25, "under25": under25, "over25_fair": over25_fair,
                    "s22": s22,
                    "pen_oui": pen_oui, "pen_non": pen_non, "pen_oui_fair": pen_oui_fair,
                    "pen_eq1": pen_eq1, "pen_eq2": pen_eq2
                }
    except Exception as e:
        return None
    return None

def main():
    print("=== DEBUT DE L'AUTOMATISATION UNIBET FRANCE (FENÊTRE 48H) ===")
    matches_to_scan = get_unibet_active_games()
    
    scanned_all = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_all.append(res)
            
    # Filter strictly for next 48 hours
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
    print(f"Total matchs retenus dans la fenêtre des 48h : {len(scanned_results)}")

    # 1. Apply Strategy Filters (ONLY RETAINED MATCHES)
    s8_matches = [r for r in scanned_results if r.get("pen_oui") and r["pen_oui"] <= SEUIL_S8]
    s4_matches = [r for r in scanned_results if r.get("over25") and r["over25"] <= SEUIL_S4]
    s3_yt_matches = [r for r in scanned_results if r.get("s22") and r["s22"] <= 12.00]
    
    s8b_bi_matches = []
    for r in scanned_results:
        p_oui, p1, p2 = r.get("pen_oui"), r.get("pen_eq1"), r.get("pen_eq2")
        if p_oui and p_oui <= SEUIL_S8 and p1 and p2 and p2 > 0:
            ratio = round(p1 / p2, 2)
            r["ratio_bi"] = ratio
            if 0.65 <= ratio <= 1.55:
                s8b_bi_matches.append(r)

    # 2. Track Odds Variations & History against previous_odds.json
    history_file = "previous_odds.json"
    prev_state = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                prev_state = json.load(f)
        except Exception:
            pass

    # Build current state maps
    curr_state = {
        "pen": {m["id"]: {"match": f"{m['dom']} - {m['ext']}", "league": m["league"], "date_str": m["date_str"], "val": m["pen_oui"], "fair": m["pen_oui_fair"]} for m in s8_matches},
        "o25": {m["id"]: {"match": f"{m['dom']} - {m['ext']}", "league": m["league"], "date_str": m["date_str"], "val": m["over25"], "fair": m["over25_fair"]} for m in s4_matches},
        "s3":  {m["id"]: {"match": f"{m['dom']} - {m['ext']}", "league": m["league"], "date_str": m["date_str"], "val": m["s22"], "over25": m.get("over25")} for m in s3_yt_matches}
    }

    # Compute evolutions for Penalty (S8)
    prev_pen = prev_state.get("pen", {})
    new_pen = [v for k, v in curr_state["pen"].items() if k not in prev_pen]
    drop_pen = [v for k, v in prev_pen.items() if k not in curr_state["pen"]]
    var_pen = []
    for k, v in curr_state["pen"].items():
        if k in prev_pen:
            old_val = prev_pen[k].get("val")
            if old_val and old_val != v["val"]:
                diff = round(v["val"] - old_val, 2)
                var_pen.append({**v, "old_val": old_val, "diff": diff})

    # Save current state to previous_odds.json
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(curr_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 3. Generate Combinés Doubles Penalty
    s8_matches.sort(key=lambda x: x.get("dt_obj", now_utc))
    combines = []
    used_teams = set()
    temp_pair = []
    for m in s8_matches:
        if m["dom"] in used_teams or m["ext"] in used_teams: continue
        temp_pair.append(m)
        used_teams.add(m["dom"])
        used_teams.add(m["ext"])
        if len(temp_pair) == 2:
            combines.append(temp_pair)
            temp_pair = []

    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')

    # 4. Build Evolutions HTML Section
    evo_html = ""
    if new_pen or var_pen or drop_pen:
        evo_html += '<div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:15px; margin-bottom:25px;">'
        evo_html += '<h3 style="color:#0f172a; margin-top:0; border-bottom:1px solid #cbd5e1; padding-bottom:5px;">📊 ÉVOLUTIONS DEPUIS LE DERNIER RUN (Il y a ~2h-3h)</h3>'
        
        if new_pen:
            evo_html += '<p style="color:#16a34a; font-weight:bold; margin-bottom:5px;">🆕 Nouveaux matchs ajoutés à la sélection Penalty :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in new_pen:
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>{item['match']}</b> (Cote Penalty: <b>{item['val']}</b>)</li>"
            evo_html += '</ul>'

        if var_pen:
            evo_html += '<p style="color:#2563eb; font-weight:bold; margin-bottom:5px;">📈📉 Variations de cotes (Penalty Oui) :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_pen:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : {item['old_val']} &rarr; <b>{item['val']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            evo_html += '</ul>'

        if drop_pen:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Matchs retirés de la sélection (seuil dépassé ou cote fermée) :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_pen:
                evo_html += f"<li><b>{item['match']}</b> ({item['league']})</li>"
            evo_html += '</ul>'
            
        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation majeure de cotes ni nouveau match depuis le dernier run.</div>'

    # 5. Build HTML Email Body (ONLY RETAINED MATCHES)
    pen_rows = ""
    for m in s8_matches:
        pen = m['pen_oui']
        pen_fair = m['pen_oui_fair']
        d_str = m['date_str']
        pen_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #f0fdf4;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #16a34a;"><b>{pen}</b> <br><small style="color:#64748b;">(Dém. {pen_fair})</small></td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #16a34a;">🟢 RETENU</td>
        </tr>
        """

    if not pen_rows:
        pen_rows = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide le critère Penalty &le; 2.90 dans les 48h.</td></tr>'

    o25_rows = ""
    for m in s4_matches:
        o25 = m['over25']
        o25_fair = m['over25_fair']
        d_str = m['date_str']
        o25_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #eff6ff;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #2563eb;"><b>{o25}</b> <br><small style="color:#64748b;">(Dém. {o25_fair})</small></td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #2563eb;">🟢 RETENU</td>
        </tr>
        """

    if not o25_rows:
        o25_rows = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide le critère Over 2.5 &le; 1.87 dans les 48h.</td></tr>'

    yt_rows = ""
    for m in s3_yt_matches:
        s22 = m['s22']
        s22_f = round(s22 * 1.15, 2)
        o25 = m.get('over25')
        o25_fair = m.get('over25_fair')
        d_str = m['date_str']
        o25_d = f"O2.5: <b>{o25}</b> <small>(Dém. {o25_fair})</small>" if o25 else "O2.5: N/A"
        yt_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #fefce8;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center; color: #b45309;">2-2: <b>{s22}</b> <small>(Dém. {s22_f})</small><br>{o25_d}</td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #d97706;">🟢 RETENU S3</td>
        </tr>
        """

    s8b_rows = ""
    for m in s8b_bi_matches:
        p_oui = m['pen_oui']
        p1 = m.get('pen_eq1', 'N/A')
        p2 = m.get('pen_eq2', 'N/A')
        ratio = m.get('ratio_bi', 'N/A')
        d_str = m['date_str']
        s8b_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #faf5ff;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center;">Global: <b>{p_oui}</b><br><small style="color:#7e22ce;">Eq1: {p1} | Eq2: {p2}</small></td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #6b21a8;">Ratio: {ratio} <small style="color:#7e22ce;">(Équilibré)</small></td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #9333ea;">⭐ DOUBLE DANGER</td>
        </tr>
        """
    if not s8b_rows:
        s8b_rows = '<tr><td colspan="6" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide le critère Option B Bi-Directionnelle (Ratio entre 0.65 et 1.55) dans les 48h.</td></tr>'

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 20px;">
        <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 10px; border: 1px solid #e2e8f0;">
          <h1 style="color: #1e3a8a; text-align: center;">⚽ METRIC-FOOT UNIBET (SELECTION 48H)</h1>
          <p style="text-align: center; color: #64748b;">Fenêtre des 48 prochaines heures ({len(scanned_results)} matchs scannés au total) - {now_str}</p>
          
          {evo_html}

          <h3 style="color: #16a34a; border-bottom: 2px solid #16a34a; padding-bottom: 5px;">🎯 AUDIT PENALTY RETENUS (SEUIL UNIBET &le; 2.90)</h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #f8fafc;">
                <th style="padding: 8px; text-align: left;">Date &amp; Horaire</th>
                <th style="padding: 8px; text-align: left;">Ligue</th>
                <th style="padding: 8px; text-align: left;">Match</th>
                <th style="padding: 8px;">Cote Pen.</th>
                <th style="padding: 8px;">Décision</th>
              </tr>
            </thead>
            <tbody>{pen_rows}</tbody>
          </table>

          <h3 style="color: #9333ea; border-bottom: 2px solid #9333ea; padding-bottom: 5px; margin-top: 30px;">⭐ OPTION B BI-DIRECTIONNELLE (DOUBLE DANGER PENALTY - STRATÉGIE 8B)</h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #f8fafc;">
                <th style="padding: 8px; text-align: left;">Date &amp; Horaire</th>
                <th style="padding: 8px; text-align: left;">Ligue</th>
                <th style="padding: 8px; text-align: left;">Match</th>
                <th style="padding: 8px;">Cotes Penalty (Eq1 / Eq2)</th>
                <th style="padding: 8px;">Ratio Symétrie</th>
                <th style="padding: 8px;">Décision</th>
              </tr>
            </thead>
            <tbody>{s8b_rows}</tbody>
          </table>

          <h4 style="color: #15803d; margin-top: 15px;">🔗 Combinés Doubles Penalty (48h)</h4>
          {combine_h}

          <h3 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 5px; margin-top: 30px;">⚡ AUDIT OVER 2.5 RETENUS (SEUIL UNIBET &le; 1.87)</h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #f8fafc;">
                <th style="padding: 8px; text-align: left;">Date &amp; Horaire</th>
                <th style="padding: 8px; text-align: left;">Ligue</th>
                <th style="padding: 8px; text-align: left;">Match</th>
                <th style="padding: 8px;">Cote O2.5</th>
                <th style="padding: 8px;">Décision</th>
              </tr>
            </thead>
            <tbody>{o25_rows}</tbody>
          </table>

          <h3 style="color: #d97706; border-bottom: 2px solid #d97706; padding-bottom: 5px; margin-top: 30px;">🎥 MÉTHODE YOUTUBE OVER 2.5 (SEUIL SCORE 2-2 &le; 12.00)</h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #f8fafc;">
                <th style="padding: 8px; text-align: left;">Date &amp; Horaire</th>
                <th style="padding: 8px; text-align: left;">Ligue</th>
                <th style="padding: 8px; text-align: left;">Match</th>
                <th style="padding: 8px;">Cotes (2-2 / O2.5)</th>
                <th style="padding: 8px;">Décision</th>
              </tr>
            </thead>
            <tbody>{yt_rows}</tbody>
          </table>
        </div>
      </body>
    </html>
    """

    # 6. Generate report.md
    report = []
    report.append("# ⚽ PARIS SPORTIFS - SELECTION 48H & SUIVI DES VARIATIONS DE COTES")
    report.append(f"**Généré le** : {now_str}\n")
    report.append("## 🎯 MATCHS PENALTY RETENUS (48h)")
    report.append("| Date & Horaire | Ligue | Match | Cote Unibet (Brut) | Cote Démargée |")
    report.append("| :---: | :--- | :--- | :---: | :---: |")
    for m in s8_matches:
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['pen_oui']}** | **{m['pen_oui_fair']}** |")
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    # 7. Email Sending logic (Gmail SMTP primary)
    recipients = [r.strip() for r in os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr, langlet.gregory@gmail.com").split(",") if r.strip()]
    gmail_email = os.environ.get("GMAIL_EMAIL", "langlet.gregory@gmail.com")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    
    sender_email = gmail_email if gmail_password else "gregory.langlet@sfr.fr"
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"PRONOSTICS FOOTBALL (48H) - UNIBET FRANCE AUDIT DU {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}"
    msg["From"] = f"Gregory LANGLET <{sender_email}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if gmail_password:
        try:
            print(f"Sending email to {recipients} via Gmail SMTP...")
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(gmail_email, gmail_password)
                server.sendmail(gmail_email, recipients, msg.as_string())
            print("SUCCESS! Email sent via Gmail SMTP.")
        except Exception as e:
            print(f"Failed sending email via Gmail SMTP: {e}")

if __name__ == "__main__":
    main()
