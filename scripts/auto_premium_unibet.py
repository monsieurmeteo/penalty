# -*- coding: utf-8 -*-
"""
Automation Module for Unibet France (ANJ Approved)
Scrapes odds for Penalty, Over 2.5, and Score 2-2 directly from Unibet.fr
"""

import requests
from bs4 import BeautifulSoup
import json, re, os, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

# Configuration
SEUIL_S8 = 2.90   # Penalty Oui <= 2.90
SEUIL_S4 = 1.87   # Over 2.5 Direct <= 1.87
SEUIL_S3 = 10.00  # Score exact 2-2 <= 10.00

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}

ALIASES = {
    "kups": "kuopion palloseura",
    "ch odessa": "chornomorets odesa",
    "st johnstone": "saint johnstone",
    "fktukums2000": "tukums 2000",
    "fkliepaja": "liepaja"
}

def clean_team_name(name):
    if not name: return ""
    n = unicodedata.normalize('NFD', str(name))
    n = "".join(c for c in n if unicodedata.category(c) != 'Mn')
    n = n.lower().strip()
    if n in ALIASES:
        return ALIASES[n]
    words = re.split(r"[\s\.\-]+", n)
    ignored = {"fc", "fk", "cs", "sd", "jk", "ff", "sc", "sk", "ac", "nk", "cd", "ca", "mfk", "msk", "rks", "gks", "vsc", "osk", "sa", "ii", "u19", "u21"}
    cleaned_words = [w for w in words if w not in ignored and len(w) > 1]
    if not cleaned_words:
        return n
    return " ".join(cleaned_words)

def sim(a, b):
    ca, cb = clean_team_name(a), clean_team_name(b)
    if ca in cb or cb in ca:
        return 0.85 + 0.15 * SequenceMatcher(None, ca, cb).ratio()
    return SequenceMatcher(None, ca, cb).ratio()

def parse_input_file(filepath):
    if not os.path.exists(filepath):
        return []
    matches = []
    current_time = ''
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            if re.match(r"^\d{2}h\d{2}$", line):
                current_time = line
            elif "-" in line:
                parts = line.split("-")
                if len(parts) == 2:
                    matches.append({"time": current_time, "home": parts[0].strip(), "away": parts[1].strip()})
    return matches

def get_unibet_active_games():
    print("Scraping Unibet France complete football catalog across all leagues...")
    main_url = "https://www.unibet.fr/paris-football"
    try:
        r = requests.get(main_url, headers=H, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        match_links = soup.find_all("a", href=lambda h: h and "/paris-football/" in h)
        
        league_paths = set()
        for a in match_links:
            href = a.get("href", "")
            parts = href.strip("/").split("/")
            if len(parts) >= 3 and not href.startswith("http"):
                league_path = f"https://www.unibet.fr/{'/'.join(parts[:3])}"
                league_paths.add(league_path)
                
        all_match_urls = set()
        for a in match_links:
            href = a.get("href", "")
            if "vs" in href and len(href.split("/")) >= 5:
                all_match_urls.add(f"https://www.unibet.fr{href}" if href.startswith("/") else href)
                
        # Crawl all league sub-pages in parallel to gather 100% of fixtures
        print(f"Crawling {len(league_paths)} league sub-pages on Unibet France...")
        def fetch_league(url):
            try:
                r_l = requests.get(url, headers=H, timeout=8)
                soup_l = BeautifulSoup(r_l.text, "html.parser")
                m_links = soup_l.find_all("a", href=lambda h: h and "/paris-football/" in h and "vs" in h)
                return [f"https://www.unibet.fr{a.get('href')}" if a.get('href').startswith("/") else a.get('href') for a in m_links]
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(fetch_league, lp) for lp in league_paths]
            for f in as_completed(futs):
                for m_url in f.result():
                    all_match_urls.add(m_url)
                    
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
                    
        print(f"Extracted {len(games)} total active football fixtures from Unibet France.")
        return games
    except Exception as e:
        print(f"Error fetching Unibet catalog: {e}")
        return []

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
                        m_desc = m.get("description", "").lower()
                        outcomes = m.get("outcomes", [])
                        
                        # 1N2
                        if m_desc == "1 n 2" or m_desc == "1n2":
                            for o in outcomes:
                                o_desc = o.get("description", "").lower()
                                price = float(o.get("price", "0").replace(",", "."))
                                if dom.lower() in o_desc: c1 = price
                                elif ext.lower() in o_desc: c2 = price
                                elif "nul" in o_desc: cx = price
                                
                        # Over / Under 2.5
                        if "plus / moins 2.5" in m_desc or "nombre de buts" in m_desc:
                            for o in outcomes:
                                o_desc = o.get("description", "").lower()
                                price = float(o.get("price", "0").replace(",", "."))
                                if "plus 2.5" in o_desc or "plus 2,5" in o_desc: over25 = price
                                elif "moins 2.5" in o_desc or "moins 2,5" in o_desc: under25 = price
                                
                        # Penalty
                        if "penalty" in m_desc:
                            for o in outcomes:
                                o_desc = o.get("description", "").lower()
                                price = float(o.get("price", "0").replace(",", "."))
                                if "une des 2" in o_desc or "oui" in o_desc:
                                    pen_oui = price
                                elif "pas de penalty" in o_desc or "non" in o_desc:
                                    pen_non = price
                                    
                        # Score 2-2
                        if "score exact" in m_desc and "mi-temps" not in m_desc:
                            for o in outcomes:
                                o_desc = o.get("description", "").strip()
                                price = float(o.get("price", "0").replace(",", "."))
                                if o_desc in ["2 - 2", "2-2"]:
                                    s22 = price
                                    
                return {
                    **game,
                    "dom": dom,
                    "ext": ext,
                    "c1": c1, "cx": cx, "c2": c2,
                    "over25": over25, "under25": under25,
                    "s22": s22,
                    "pen_oui": pen_oui, "pen_non": pen_non
                }
    except Exception as e:
        return None
    return None

def main():
    print("=== DEBUT DE L'AUTOMATISATION UNIBET FRANCE ===")
    parsed_input = parse_input_file("matches_input.txt")
    unibet_games = get_unibet_active_games()
    
    matches_to_scan = []
    seen_ids = set()
    unmatched_count = 0
    
    for p in parsed_input:
        best, best_sc = None, 0
        for g in unibet_games:
            sc_direct = (sim(p["home"], g["dom"]) + sim(p["away"], g["ext"])) / 2
            sc_inverse = (sim(p["home"], g["ext"]) + sim(p["away"], g["dom"])) / 2
            sc_final = max(sc_direct, sc_inverse)
            if sc_final > best_sc:
                best_sc = sc_final
                best = g
        if best and best_sc >= 0.58:
            if best["id"] in seen_ids: continue
            seen_ids.add(best["id"])
            if p["time"]: best["start_time"] = f"{p['time']}"
            matches_to_scan.append(best)
        else:
            unmatched_count += 1
            matches_to_scan.append({
                "id": f"unmatched_{unmatched_count}",
                "dom": p["home"],
                "ext": p["away"],
                "league": "Pronosoft (Non rattaché)",
                "start_time": f"{p['time']}" if p['time'] else "Pronosoft",
                "timestamp": int(time.time()) + 86400,
                "not_found": True
            })
            
    print(f"Total matchs à auditer sur Unibet.fr : {len(matches_to_scan)}")
    
    scanned_results = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_results.append(res)
            
    scanned_results.sort(key=lambda x: x["timestamp"])
    
    # 3. Apply Strategies
    s4_matches = [r for r in scanned_results if r.get("over25") and r["over25"] <= SEUIL_S4]
    s8_matches = [r for r in scanned_results if r.get("pen_oui") and r["pen_oui"] <= SEUIL_S8]
    
    # 4. Generate Combinés Doubles
    s8_matches.sort(key=lambda x: x["timestamp"])
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
            
    # 5. Generate Markdown Report
    report = []
    report.append(f"# ⚽ PARIS SPORTIFS - AUDIT ET STRATÉGIES AUTOMATISÉES (UNIBET FRANCE 🇫🇷)")
    report.append(f"**Généré le** : {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')}\n")
    report.append("─" * 50 + "\n")
    
    report.append(f"## 🎯 AUDIT PENALTY : TOUS LES MATCHS SCANNÉS (SEUIL ≤ {SEUIL_S8})")
    report.append("| Horaire | Championnat | Match | Cote Penalty | Décision / Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: |")
    for m in scanned_results:
        pen = m.get('pen_oui')
        if m.get("not_found"):
            decision = "🔴 NON TROUVÉ (UNIBET)"
            cote_str = "N/A"
        elif pen and pen <= SEUIL_S8:
            decision = "🟢 **RETENU**"
            cote_str = f"**{pen}**"
        elif pen:
            decision = "⚪ ÉLIMINÉ (> 2.90)"
            cote_str = f"{pen}"
        else:
            decision = "❌ NON PROPOSÉ"
            cote_str = "N/A"
        report.append(f"| {m['start_time']} | {m['league']} | {m['dom']} vs {m['ext']} | {cote_str} | {decision} |")
        
    report.append("\n" + "─" * 50 + "\n")
    
    report.append(f"### 🔗 COMBINÉS DOUBLE DE LA SESSION (Matchs Retenus)")
    if combines:
        for idx, pair in enumerate(combines, 1):
            cote_tot = round(pair[0]["pen_oui"] * pair[1]["pen_oui"], 2)
            report.append(f"**Double {idx} (Cote globale: {cote_tot})** :")
            report.append(f"*   {pair[0]['start_time']} : {pair[0]['dom']} vs {pair[0]['ext']} (Cote: {pair[0]['pen_oui']})")
            report.append(f"*   {pair[1]['start_time']} : {pair[1]['dom']} vs {pair[1]['ext']} (Cote: {pair[1]['pen_oui']})")
            report.append("")
    else:
        report.append("*Aucun combiné double disponible.*")
        
    report.append("\n" + "─" * 50 + "\n")
    
    report.append(f"## ⚡ AUDIT OVER 2.5 : TOUS LES MATCHS SCANNÉS (SEUIL ≤ {SEUIL_S4})")
    report.append("| Horaire | Championnat | Match | Cote Over 2.5 | Décision / Statut |")
    report.append("| :---: | :--- | :--- | :---: | :---: |")
    for m in scanned_results:
        o25 = m.get('over25')
        if m.get("not_found"):
            decision = "🔴 NON TROUVÉ (UNIBET)"
            cote_str = "N/A"
        elif o25 and o25 <= SEUIL_S4:
            decision = "🟢 **RETENU**"
            cote_str = f"**{o25}**"
        elif o25:
            decision = "⚪ ÉLIMINÉ (> 1.87)"
            cote_str = f"{o25}"
        else:
            decision = "❌ NON PROPOSÉ"
            cote_str = "N/A"
        report.append(f"| {m['start_time']} | {m['league']} | {m['dom']} vs {m['ext']} | {cote_str} | {decision} |")
        
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
        
    print("Report generated successfully and saved to report.md!")

    # Send Email if SMTP configured
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASS = os.environ.get("SMTP_PASS")
    EMAIL_TO = os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr")
    
    if SMTP_USER and SMTP_PASS:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')
            
            pen_rows = ""
            for m in scanned_results:
                pen = m.get('pen_oui')
                if m.get("not_found"):
                    pill_bg, pill_color, badge_text, cote_display = "#fef2f2", "#dc2626", "🔴 NON TROUVÉ", "N/A"
                elif pen and pen <= SEUIL_S8:
                    pill_bg, pill_color, badge_text, cote_display = "#f0fdf4", "#16a34a", "🟢 RETENU", f"{pen}"
                elif pen:
                    pill_bg, pill_color, badge_text, cote_display = "#f8fafc", "#64748b", "⚪ ÉLIMINÉ (> 2.90)", f"{pen}"
                else:
                    pill_bg, pill_color, badge_text, cote_display = "#fff1f2", "#94a3b8", "❌ NON PROPOSÉ", "N/A"
                pen_rows += f"""
                <tr style="border-bottom: 1px solid #e2e8f0;">
                  <td style="padding: 10px; font-weight: bold; color: #475569;">{m['start_time']}</td>
                  <td style="padding: 10px; color: #334155;">{m['league']}</td>
                  <td style="padding: 10px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                  <td style="padding: 10px; text-align: center; font-weight: bold; color: #16a34a; background-color: #f0fdf4; border-radius: 6px;">{cote_display}</td>
                  <td style="padding: 10px; text-align: center; font-weight: bold; color: {pill_color}; background-color: {pill_bg}; border-radius: 6px;">{badge_text}</td>
                </tr>
                """
                
            o25_rows = ""
            for m in scanned_results:
                o25 = m.get('over25')
                if m.get("not_found"):
                    pill_bg, pill_color, badge_text, cote_display = "#fef2f2", "#dc2626", "🔴 NON TROUVÉ", "N/A"
                elif o25 and o25 <= SEUIL_S4:
                    pill_bg, pill_color, badge_text, cote_display = "#eff6ff", "#2563eb", "🟢 RETENU", f"{o25}"
                elif o25:
                    pill_bg, pill_color, badge_text, cote_display = "#f8fafc", "#64748b", "⚪ ÉLIMINÉ (> 1.87)", f"{o25}"
                else:
                    pill_bg, pill_color, badge_text, cote_display = "#fff1f2", "#94a3b8", "❌ NON PROPOSÉ", "N/A"
                o25_rows += f"""
                <tr style="border-bottom: 1px solid #e2e8f0;">
                  <td style="padding: 10px; font-weight: bold; color: #475569;">{m['start_time']}</td>
                  <td style="padding: 10px; color: #334155;">{m['league']}</td>
                  <td style="padding: 10px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                  <td style="padding: 10px; text-align: center; font-weight: bold; color: #2563eb; background-color: #eff6ff; border-radius: 6px;">{cote_display}</td>
                  <td style="padding: 10px; text-align: center; font-weight: bold; color: {pill_color}; background-color: {pill_bg}; border-radius: 6px;">{badge_text}</td>
                </tr>
                """

            html_body = f"""
            <html>
              <body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 20px;">
                <div style="max-width: 650px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 10px; border: 1px solid #e2e8f0;">
                  <h1 style="color: #1e3a8a; text-align: center;">\u26bd METRIC-FOOT UNIBET FRANCE 🇫🇷</h1>
                  <p style="text-align: center; color: #64748b;">Rapport du {now_str}</p>
                  
                  <h3 style="color: #16a34a;">🎯 AUDIT PENALTY (SEUIL &le; {SEUIL_S8})</h3>
                  <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                      <tr style="background: #f8fafc;">
                        <th style="padding: 8px; text-align: left;">Horaire</th>
                        <th style="padding: 8px; text-align: left;">Ligue</th>
                        <th style="padding: 8px; text-align: left;">Match</th>
                        <th style="padding: 8px;">Cote Pen.</th>
                        <th style="padding: 8px;">Décision</th>
                      </tr>
                    </thead>
                    <tbody>{pen_rows}</tbody>
                  </table>

                  <h3 style="color: #2563eb; margin-top: 25px;">⚡ AUDIT OVER 2.5 (SEUIL &le; {SEUIL_S4})</h3>
                  <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                      <tr style="background: #f8fafc;">
                        <th style="padding: 8px; text-align: left;">Horaire</th>
                        <th style="padding: 8px; text-align: left;">Ligue</th>
                        <th style="padding: 8px; text-align: left;">Match</th>
                        <th style="padding: 8px;">Cote O2.5</th>
                        <th style="padding: 8px;">Décision</th>
                      </tr>
                    </thead>
                    <tbody>{o25_rows}</tbody>
                  </table>
                </div>
              </body>
            </html>
            """
            
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"\u26bd [UNIBET FR] Pronostics Foot & Audit - {now_str}"
            msg["From"] = SMTP_USER
            msg["To"] = EMAIL_TO
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            email_sent = False
            # Try Port 465 SSL first (bypasses Spamhaus port 587 filter on cloud runners)
            try:
                print("Attempting email send via SFR SMTP SSL (port 465)...")
                server = smtplib.SMTP_SSL("smtp.sfr.fr", 465, timeout=15)
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
                server.quit()
                print("Email sent successfully via SFR SMTP SSL (port 465).")
                email_sent = True
            except Exception as e_ssl:
                print(f"Port 465 SSL attempt failed ({e_ssl}), falling back to Port 587 TLS...")
                
            if not email_sent:
                server = smtplib.SMTP("smtp.sfr.fr", 587, timeout=15)
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
                server.quit()
                print("Email sent successfully via SFR SMTP TLS (port 587).")
        except Exception as e:
            print(f"Failed to send email: {e}")

if __name__ == "__main__":
    main()
