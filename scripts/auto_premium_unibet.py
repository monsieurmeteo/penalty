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
            
    # Also fetch main football page links
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
            
        c1 = cx = c2 = over25 = under25 = s22 = pen_oui = pen_non = None
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
                                    
                        if "penalty" in m_desc and pen_oui is None:
                            for o in outcomes:
                                o_desc = (o.get("description") or "").lower()
                                p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                                if "une des 2" in o_desc or "oui" in o_desc: pen_oui = p_val
                                elif "non" in o_desc or "pas de penalty" in o_desc: pen_non = p_val
                                
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
                    "pen_oui": pen_oui, "pen_non": pen_non, "pen_oui_fair": pen_oui_fair
                }
    except Exception as e:
        return None
    return None

def main():
    print("=== DEBUT DE L'AUTOMATISATION UNIBET FRANCE ===")
    matches_to_scan = get_unibet_active_games()
    print(f"Total matchs à auditer sur Unibet.fr : {len(matches_to_scan)}")
    
    scanned_results = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_results.append(res)
            
    scanned_results.sort(key=lambda x: x.get("start_iso", ""))
    
    # 1. Apply Strategies
    s4_matches = [r for r in scanned_results if r.get("over25") and r["over25"] <= SEUIL_S4]
    s8_matches = [r for r in scanned_results if r.get("pen_oui") and r["pen_oui"] <= SEUIL_S8]
    s3_yt_matches = [r for r in scanned_results if r.get("s22") and r["s22"] <= 12.00 and r.get("over25") and r["over25"] <= SEUIL_S4]
    
    # 2. Generate Combinés Doubles
    s8_matches.sort(key=lambda x: x.get("start_iso", ""))
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
            
    # 3. Generate Markdown Report
    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')
    report = []
    report.append(f"# ⚽ PARIS SPORTIFS - AUDIT ET STRATÉGIES AUTOMATISÉES (UNIBET FRANCE 🇫🇷)")
    report.append(f"**Généré le** : {now_str}\n")
    report.append("─" * 50 + "\n")
    
    # Section Penalty (S8)
    report.append(f"## 🎯 AUDIT PENALTY : TOUS LES MATCHS SCANNÉS (SEUIL UNIBET ≤ {SEUIL_S8})")
    report.append("| Date & Horaire | Championnat | Match | Cote Unibet (Brut) | Cote Démargée (Équiv. 1XBET) | Décision / Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: |")
    
    for m in scanned_results:
        pen = m.get('pen_oui')
        pen_fair = m.get('pen_oui_fair')
        d_str = m.get('date_str', 'À venir')
        if pen and pen <= SEUIL_S8:
            decision = "🟢 **RETENU**"
            cote_str, fair_str = f"**{pen}**", f"**{pen_fair}**"
        elif pen:
            decision = "⚪ ÉLIMINÉ (> 2.90)"
            cote_str, fair_str = f"{pen}", f"{pen_fair}"
        else:
            decision = "❌ NON PROPOSÉ"
            cote_str, fair_str = "N/A", "N/A"
        report.append(f"| {d_str} | {m['league']} | {m['dom']} vs {m['ext']} | {cote_str} | {fair_str} | {decision} |")
        
    report.append("\n" + "─" * 50 + "\n")
    report.append("### 🔗 COMBINÉS DOUBLE DE LA SESSION (Matchs Retenus)")
    if combines:
        for idx, pair in enumerate(combines, 1):
            cote_globale = round(pair[0]["pen_oui"] * pair[1]["pen_oui"], 2)
            report.append(f"**Double {idx} (Cote globale: {cote_globale})** :")
            report.append(f"*   {pair[0].get('date_str')} : {pair[0]['dom']} vs {pair[0]['ext']} (Cote Unibet: {pair[0]['pen_oui']}, Démargée: {pair[0]['pen_oui_fair']})")
            report.append(f"*   {pair[1].get('date_str')} : {pair[1]['dom']} vs {pair[1]['ext']} (Cote Unibet: {pair[1]['pen_oui']}, Démargée: {pair[1]['pen_oui_fair']})\n")
    else:
        report.append("Aucun combiné double disponible sur cette session.\n")
        
    report.append("─" * 50 + "\n")
    
    # Section Over 2.5 (S4)
    report.append(f"## ⚡ AUDIT OVER 2.5 : TOUS LES MATCHS SCANNÉS (SEUIL UNIBET ≤ {SEUIL_S4})")
    report.append("| Date & Horaire | Championnat | Match | Cote Unibet (Brut) | Cote Démargée (Équiv. 1XBET) | Décision / Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: |")
    
    for m in scanned_results:
        o25 = m.get('over25')
        o25_fair = m.get('over25_fair')
        d_str = m.get('date_str', 'À venir')
        if o25 and o25 <= SEUIL_S4:
            decision = "🟢 **RETENU**"
            cote_str, fair_str = f"**{o25}**", f"**{o25_fair}**"
        elif o25:
            decision = "⚪ ÉLIMINÉ (> 1.87)"
            cote_str, fair_str = f"{o25}", f"{o25_fair}"
        else:
            decision = "❌ NON PROPOSÉ"
            cote_str, fair_str = "N/A", "N/A"
        report.append(f"| {d_str} | {m['league']} | {m['dom']} vs {m['ext']} | {cote_str} | {fair_str} | {decision} |")

    report.append("\n" + "─" * 50 + "\n")

    # Section YouTube Over 2.5 (S3)
    report.append(f"## 🎥 MÉTHODE YOUTUBE OVER 2.5 (SEUIL SCORE 2-2 ≤ 12.00 & OVER 2.5 ≤ 1.87)")
    report.append("| Date & Horaire | Championnat | Match | Cote Score 2-2 | Cote Over 2.5 | Décision / Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: | :---: |")
    
    for m in scanned_results:
        s22 = m.get('s22')
        o25 = m.get('over25')
        d_str = m.get('date_str', 'À venir')
        if s22 and s22 <= 12.00 and o25 and o25 <= SEUIL_S4:
            decision = "🟢 **RETENU S3**"
            s22_str, o25_str = f"**{s22}**", f"**{o25}**"
            report.append(f"| {d_str} | {m['league']} | {m['dom']} vs {m['ext']} | {s22_str} | {o25_str} | {decision} |")

    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
        
    print("Report generated successfully and saved to report.md!")

    # 4. Email Sending logic
    recipients = [r.strip() for r in os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr, langlet.gregory@gmail.com").split(",") if r.strip()]
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    
    # Try reading mail skill config if env vars are empty
    if not SMTP_USER or not SMTP_PASS:
        try:
            cfg_p = r"C:\Users\grego\.gemini\config\skills\mail\config.json"
            if os.path.exists(cfg_p):
                with open(cfg_p, "r", encoding="utf-8") as f_cfg:
                    cfg_data = json.load(f_cfg)
                    SMTP_USER = cfg_data.get("email", "")
                    SMTP_PASS = cfg_data.get("password", "")
        except Exception:
            pass

    if SMTP_USER and SMTP_PASS:
        try:
            pen_rows = ""
            for m in scanned_results:
                pen = m.get('pen_oui')
                pen_fair = m.get('pen_oui_fair')
                d_str = m.get('date_str', 'À venir')
                if pen and pen <= SEUIL_S8:
                    badge = '<span style="color:#16a34a; font-weight:bold;">🟢 RETENU</span>'
                    cote_d = f"<b>{pen}</b> <br><small style='color:#64748b;'>(Dém. {pen_fair})</small>"
                    bg = 'background-color: #f0fdf4;'
                elif pen:
                    badge = '<span style="color:#64748b;">⚪ ÉLIMINÉ</span>'
                    cote_d = f"{pen}"
                    bg = ''
                else:
                    badge = '<span style="color:#94a3b8;">❌ NON PROPOSÉ</span>'
                    cote_d = 'N/A'
                    bg = ''
                pen_rows += f"""
                <tr style="border-bottom: 1px solid #e2e8f0; {bg}">
                  <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
                  <td style="padding: 8px; color: #334155;">{m['league']}</td>
                  <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                  <td style="padding: 8px; text-align: center;">{cote_d}</td>
                  <td style="padding: 8px; text-align: center;">{badge}</td>
                </tr>
                """

            o25_rows = ""
            for m in scanned_results:
                o25 = m.get('over25')
                o25_fair = m.get('over25_fair')
                d_str = m.get('date_str', 'À venir')
                if o25 and o25 <= SEUIL_S4:
                    badge = '<span style="color:#2563eb; font-weight:bold;">🟢 RETENU</span>'
                    cote_d = f"<b>{o25}</b> <br><small style='color:#64748b;'>(Dém. {o25_fair})</small>"
                    bg = 'background-color: #eff6ff;'
                elif o25:
                    badge = '<span style="color:#64748b;">⚪ ÉLIMINÉ</span>'
                    cote_d = f"{o25}"
                    bg = ''
                else:
                    badge = '<span style="color:#94a3b8;">❌ NON PROPOSÉ</span>'
                    cote_d = 'N/A'
                    bg = ''
                o25_rows += f"""
                <tr style="border-bottom: 1px solid #e2e8f0; {bg}">
                  <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
                  <td style="padding: 8px; color: #334155;">{m['league']}</td>
                  <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                  <td style="padding: 8px; text-align: center;">{cote_d}</td>
                  <td style="padding: 8px; text-align: center;">{badge}</td>
                </tr>
                """

            yt_rows = ""
            yt_c = 0
            for m in scanned_results:
                s22 = m.get('s22')
                o25 = m.get('over25')
                o25_fair = m.get('over25_fair')
                d_str = m.get('date_str', 'À venir')
                if s22 and s22 <= 12.00 and o25 and o25 <= SEUIL_S4:
                    yt_c += 1
                    s22_f = round(s22 * 1.15, 2)
                    yt_rows += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0; background-color: #fefce8;">
                      <td style="padding: 8px; font-weight: bold; color: #475569;">{d_str}</td>
                      <td style="padding: 8px; color: #334155;">{m['league']}</td>
                      <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                      <td style="padding: 8px; text-align: center; color: #b45309;">2-2: <b>{s22}</b> <small>(Dém. {s22_f})</small><br>O2.5: <b>{o25}</b> <small>(Dém. {o25_fair})</small></td>
                      <td style="padding: 8px; text-align: center; font-weight: bold; color: #d97706;">🟢 RETENU S3</td>
                    </tr>
                    """

            if yt_c == 0:
                yt_rows = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide la combinaison Score 2-2 &le; 12.00 + Over 2.5 &le; 1.87.</td></tr>'

            combine_h = ""
            if combines:
                for idx, pair in enumerate(combines, 1):
                    c_tot = round(pair[0]["pen_oui"] * pair[1]["pen_oui"], 2)
                    combine_h += f"""
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; margin-bottom: 10px;">
                      <b style="color: #16a34a;">Double #{idx} (Cote Globale Unibet: {c_tot})</b>
                      <ul style="margin: 5px 0 0 0; padding-left: 20px; font-size: 13px; color: #1e293b;">
                        <li><b>{pair[0].get('date_str')}</b> : {pair[0]['dom']} vs {pair[0]['ext']} (Cote Penalty: <b>{pair[0]['pen_oui']}</b>)</li>
                        <li><b>{pair[1].get('date_str')}</b> : {pair[1]['dom']} vs {pair[1]['ext']} (Cote Penalty: <b>{pair[1]['pen_oui']}</b>)</li>
                      </ul>
                    </div>
                    """
            else:
                combine_h = "<p style='color:#64748b;'>Pas assez de matchs penalty retenus pour former un combiné double.</p>"

            html_body = f"""
            <html>
              <body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 20px;">
                <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 10px; border: 1px solid #e2e8f0;">
                  <h1 style="color: #1e3a8a; text-align: center;">⚽ METRIC-FOOT UNIBET FRANCE (DEEP CATALOG 330+ MATCHS)</h1>
                  <p style="text-align: center; color: #64748b;">Rapport d'analyse global ({len(scanned_results)} matchs au programme) - {now_str}</p>
                  
                  <h3 style="color: #16a34a; border-bottom: 2px solid #16a34a; padding-bottom: 5px;">🎯 AUDIT PENALTY (SEUIL UNIBET &le; 2.90)</h3>
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

                  <h4 style="color: #15803d; margin-top: 15px;">🔗 Combinés Doubles Penalty</h4>
                  {combine_h}

                  <h3 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 5px; margin-top: 30px;">⚡ AUDIT OVER 2.5 (SEUIL UNIBET &le; 1.87)</h3>
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

                  <h3 style="color: #d97706; border-bottom: 2px solid #d97706; padding-bottom: 5px; margin-top: 30px;">🎥 MÉTHODE YOUTUBE OVER 2.5 (Score 2-2 &le; 12.00 &amp; Over 2.5 &le; 1.87)</h3>
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
            
            gmail_email = os.environ.get("GMAIL_EMAIL", "langlet.gregory@gmail.com")
            gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
            
            sender_email = gmail_email if gmail_password else SMTP_USER
            
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"PRONOSTICS FOOTBALL - UNIBET FRANCE DEEP AUDIT DU {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}"
            msg["From"] = f"Gregory LANGLET <{sender_email}>"
            msg["To"] = ", ".join(recipients)
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            email_sent = False
            
            if gmail_password:
                try:
                    print(f"Attempting email send to {recipients} via Gmail SMTP (smtp.gmail.com:587)...")
                    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(gmail_email, gmail_password)
                        server.sendmail(gmail_email, recipients, msg.as_string())
                    print("SUCCESS! Email sent via Gmail SMTP.")
                    email_sent = True
                except Exception as e_gmail:
                    print(f"Gmail SMTP attempt failed: {e_gmail}")
                    
            if not email_sent:
                SMTP_HOST = os.environ.get("SMTP_HOST", os.environ.get("SMTP_SERVER", "smtp.sfr.fr"))
                SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
                
                if SMTP_PORT == 465:
                    try:
                        print(f"Attempting email send to {recipients} via {SMTP_HOST}:{SMTP_PORT} SSL...")
                        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15)
                        server.login(SMTP_USER, SMTP_PASS)
                        server.sendmail(SMTP_USER, recipients, msg.as_string())
                        server.quit()
                        print(f"Email sent successfully via {SMTP_HOST} SSL.")
                        email_sent = True
                    except Exception as e_ssl:
                        print(f"Port 465 SSL attempt failed: {e_ssl}")
                        
                if not email_sent:
                    try:
                        print(f"Attempting email send to {recipients} via {SMTP_HOST}:587 TLS...")
                        server = smtplib.SMTP(SMTP_HOST, 587, timeout=15)
                        server.starttls()
                        server.login(SMTP_USER, SMTP_PASS)
                        server.sendmail(SMTP_USER, recipients, msg.as_string())
                        server.quit()
                        print(f"Email sent successfully via {SMTP_HOST} TLS.")
                        email_sent = True
                    except Exception as e_tls:
                        print(f"TLS attempt failed: {e_tls}")
        except Exception as e:
            print(f"Failed to send email: {e}")

if __name__ == "__main__":
    main()
