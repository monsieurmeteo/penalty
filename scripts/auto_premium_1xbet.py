import gzip, json, re, sys, time, os
from datetime import datetime, timezone, timedelta

def get_paris_time_str(ts=None, fmt='%d/%m à %H:%M'):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Paris")
        dt = datetime.now(tz) if ts is None else datetime.fromtimestamp(ts, tz=tz)
    except Exception:
        tz = timezone(timedelta(hours=2))
        dt = datetime.now(timezone.utc).astimezone(tz) if ts is None else datetime.fromtimestamp(ts, timezone.utc).astimezone(tz)
    return dt.strftime(fmt)

from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

try:
    from curl_cffi import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "curl_cffi", "-q"], check=True)
    from curl_cffi import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MIRRORS = [
    "https://al-1xbet.com",
    "https://ar-1xbet.com",
    "https://an-1xbet.com",
    "https://ua-1xbet.com",
    "https://1xbet.com"
]
BASE = "https://ar-1xbet.com/service-api"  # Working default fallback
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Referer": "https://ar-1xbet.com/fr/line/football",
    "X-Requested-With": "XMLHttpRequest",
}

def initialize_working_mirror():
    global BASE
    print("Testing 1XBET mirrors to find a working host...")
    for m in MIRRORS:
        url = f"{m}/service-api/LineFeed/GetSportsZip?lng=fr"
        try:
            r = requests.get(url, headers={**H, "Referer": f"{m}/fr/line/football"}, impersonate="chrome120", timeout=5)
            if r.status_code == 200:
                print(f"-> Selected working mirror: {m}")
                BASE = f"{m}/service-api"
                H["Referer"] = f"{m}/fr/line/football"
                return True
        except:
            pass
    print("WARNING: No responsive mirrors found, using default fallback.")
    return False

SEUIL_S3 = 10.00   # Score exact 2-2 <= 10.00 (YouTube)
SEUIL_S4 = 1.87    # Over 2.5 directe <= 1.87
SEUIL_S8 = 2.90    # Penalty Oui <= 2.90

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO", "gregory.langlet@sfr.fr")

# Prioritize major divisions where penalty markets are open pre-match
PRIORITY_LEAGUES = [
    "Angleterre", "Espagne", "Italie", "Allemagne", "France", "Pays-Bas", "Belgique", "Portugal",
    "Brésil", "Argentine", "Norvège", "Suède", "Danemark", "Turquie", "Mexique", "Japon", "Corée du Sud",
    "Chili", "Colombie", "Équateur", "Pologne", "Autriche", "Suisse", "Écosse", "Russie", "Ukraine"
]

def sim(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    if a in b or b in a: return 0.85 + 0.15 * SequenceMatcher(None, a, b).ratio()
    return SequenceMatcher(None, a, b).ratio()

def fetch_url(url, timeout=15, retries=5):
    for i in range(retries):
        try:
            r = requests.get(url, headers=H, impersonate="chrome120", timeout=timeout)
            if r.status_code == 200:
                content = gzip.decompress(r.content) if r.content[:2] == b'\x1f\x8b' else r.content
                return json.loads(content)
        except Exception as e:
            if i == retries - 1:
                print(f"Failed to fetch {url} after {retries} retries. Error: {e}")
            time.sleep(1.0)
    return None

def get_active_games():
    """Fetches all leagues and filters games for the next 36h."""
    sports = fetch_url(f"{BASE}/LineFeed/GetSportsZip?lng=fr")
    if not sports:
        return []
        
def get_active_games(scan_all_leagues=False):
    """Fetches all leagues and filters games for the next 36h."""
    sports = fetch_url(f"{BASE}/LineFeed/GetSportsZip?lng=fr")
    if not sports:
        return []
        
    leagues = []
    for s in sports.get("Value", []):
        if s.get("I") == 1: # Football
            leagues = [{"id": l["LI"], "name": l["L"]} for l in s.get("L", [])]
            break
            
    # Filter target leagues
    selected_leagues = []
    for lg in leagues:
        if scan_all_leagues:
            selected_leagues.append(lg)
        else:
            name = lg["name"].lower()
            if any(p.lower() in name for p in PRIORITY_LEAGUES) and ("division" in name or "league" in name or "serie" in name or "bundesliga" in name or "primera" in name or "eliteserien" in name or "allsvenskan" in name or "superliga" in name or "championnat" in name or "coupe" in name):
                selected_leagues.append(lg)
            
    print(f"Leagues selected: {len(selected_leagues)}")
    
    all_games = []
    now_ts = int(time.time())
    
    # Fetch games for selected leagues in parallel or loop
    # If scanning all leagues, limit to 250 leagues to avoid performance bottleneck
    target_leagues = selected_leagues if not scan_all_leagues else selected_leagues[:250]
    
    def process_lg(lg):
        games = []
        d = fetch_url(f"{BASE}/LineFeed/GetChampZip?champ={lg['id']}&lng=fr", timeout=8, retries=2)
        if d:
            for g in d.get("Value", {}).get("G", []):
                st = g.get("S", 0)
                if now_ts < st < now_ts + 129600:
                    games.append({
                        "dom": g["O1"],
                        "ext": g["O2"],
                        "id": g["I"],
                        "league": lg["name"],
                        "start_time": get_paris_time_str(st),
                        "timestamp": st
                    })
        return games

    with ThreadPoolExecutor(max_workers=25) as ex:
        results = ex.map(process_lg, target_leagues)
        for g_list in results:
            all_games.extend(g_list)
            
    return all_games

def parse_input_file(filepath):
    """Parses matches_input.txt if it exists."""
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

def scan_match_details(game_info):
    try:
        url = f"{BASE}/LineFeed/GetGameZip?id={game_info['id']}&lng=fr"
        data = fetch_url(url, timeout=10, retries=3)
        if not data: return None
        val = data.get("Value", {})
        outcomes = val.get("E", [])
        
        # Extract odds
        c1 = c2 = cx = over25 = under25 = s22 = pen_oui = pen_non = eq1_pen = eq2_pen = None
        for o in outcomes:
            G, T, C, P = o.get("G"), o.get("T"), o.get("C"), o.get("P")
            if T == 1: c1 = C
            if T == 2: cx = C
            if T == 3: c2 = C
            if T == 9 and P == 2.5: over25 = C
            if T == 10 and P == 2.5: under25 = C
            if T == 8617 and str(P) == "2.002": s22 = C
            if G == 50:
                if T == 518: pen_oui = C
                if T == 519: pen_non = C
            if G == 10161 and T == 179: eq1_pen = C
            if G == 10084 and T == 10326: eq2_pen = C
            
        ratio = None
        if eq1_pen and eq2_pen:
            ratio = round(eq1_pen / eq2_pen, 2)
            
        return {
            **game_info,
            "c1": c1, "cx": cx, "c2": c2,
            "over25": over25, "under25": under25,
            "s22": s22,
            "pen_oui": pen_oui, "pen_non": pen_non,
            "eq1_pen": eq1_pen, "eq2_pen": eq2_pen,
            "ratio": ratio
        }
    except Exception as e:
        return None

def main():
    print("=== DEBUT DE L'AUTOMATISATION PREMIUM ===")
    initialize_working_mirror()
    
    # 1. Parse Input File or Auto-Scan
    matches_to_scan = []
    input_file = "matches_input.txt"
    parsed_input = parse_input_file(input_file)
    
    if parsed_input:
        print(f"Fichier matches_input.txt trouvé avec {len(parsed_input)} matchs.")
        active_games = get_active_games(scan_all_leagues=True)
        for p in parsed_input:
            best, best_sc = None, 0
            for g in active_games:
                sc = (sim(p["home"], g["dom"]) + sim(p["away"], g["ext"])) / 2
                if sc > best_sc:
                    best_sc = sc
                    best = g
            if best and best_sc >= 0.52:
                # Keep user custom horaire along with actual date
                if p["time"]: 
                    best["start_time"] = f"{get_paris_time_str(best['timestamp'], '%d/%m')} à {p['time']}"
                matches_to_scan.append(best)
    else:
        print("matches_input.txt absent ou vide. Lancement du Scan Automatique des ligues majeures...")
        matches_to_scan = get_active_games(scan_all_leagues=False)
        
    print(f"Total matchs à auditer : {len(matches_to_scan)}")
    
    # 2. Extract Data in Parallel
    scanned_results = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        futs = [ex.submit(scan_match_details, g) for g in matches_to_scan]
        for f in as_completed(futs):
            res = f.result()
            if res:
                scanned_results.append(res)
                
    scanned_results.sort(key=lambda x: x["timestamp"])
    
    # 3. Apply Strategies
    s3_matches = []
    s4_matches = []
    s8_matches = []
    all_pen_matches = []
    
    for r in scanned_results:
        # S3 YouTube: 2-2 <= 10.00
        if r.get("s22") and r["s22"] <= SEUIL_S3:
            s3_matches.append(r)
        # S4 Cote Directe Over 2.5 <= 1.87
        if r.get("over25") and r["over25"] <= SEUIL_S4:
            s4_matches.append(r)
        # All Penalty matches
        if r.get("pen_oui"):
            all_pen_matches.append(r)
            if r["pen_oui"] <= SEUIL_S8:
                s8_matches.append(r)
                
    # 4. Generate Combinés Doubles for Penalty (Retained matches only)
    s8_matches.sort(key=lambda x: x["timestamp"])
    all_pen_matches.sort(key=lambda x: x["pen_oui"])
    
    combines = []
    used_teams = set()
    temp_pair = []
    
    for m in s8_matches:
        if m["dom"] in used_teams or m["ext"] in used_teams:
            continue
        temp_pair.append(m)
        used_teams.add(m["dom"])
        used_teams.add(m["ext"])
        if len(temp_pair) == 2:
            combines.append(temp_pair)
            temp_pair = []
            
    # 5. Format Report
    now_str = get_paris_time_str(fmt='%d/%m/%Y à %H:%M')
    report = []
    report.append(f"# ⚽ RAPPORT AUTOMATIQUE METRIC-FOOT PREMIUM")
    report.append(f"Généré le {now_str}\n")
    
    # section 8: Penalty Cote Directe
    report.append(f"## 🎯 TOUS LES MATCHS PENALTY DÉTECTÉS (SEUIL SELECTION ≤ {SEUIL_S8})")
    if all_pen_matches:
        report.append("| Horaire | Championnat | Match | Cote Penalty | Décision |")
        report.append("| :---: | :--- | :--- | :---: | :---: |")
        for m in all_pen_matches:
            decision = "🟢 **RETENU**" if m['pen_oui'] <= SEUIL_S8 else "⚪ ÉLIMINÉ (> 2.90)"
            report.append(f"| {m['start_time']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['pen_oui']}** | {decision} |")
    else:
        report.append("*Aucun match avec marché Penalty disponible.*")
    report.append("")
    
    # section 8: Combinés
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
    
    # section 3: YouTube
    report.append(f"## 🎥 STRATÉGIE 3 : OVER 2.5 YOUTUBE (Score 2-2 ≤ {SEUIL_S3})")
    if s3_matches:
        report.append("| Horaire | Championnat | Match | Cote 2-2 | Over 2.5 Direct |")
        report.append("| :---: | :--- | :--- | :---: | :---: |")
        for m in s3_matches:
            report.append(f"| {m['start_time']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['s22']}** | {m.get('over25', 'N/A')} |")
    else:
        report.append("*Aucun match éligible trouvé.*")
    report.append("\n" + "─" * 50 + "\n")
    
    # section 4: Cote Directe
    report.append(f"## 🎯 STRATÉGIE 4 : OVER 2.5 COTE DIRECTE (Cote ≤ {SEUIL_S4})")
    if s4_matches:
        report.append("| Horaire | Championnat | Match | Cote Over 2.5 |")
        report.append("| :---: | :--- | :--- | :---: |")
        for m in s4_matches:
            report.append(f"| {m['start_time']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['over25']}** |")
    else:
        report.append("*Aucun match éligible trouvé.*")
        
    report_content = "\n".join(report)
    
    # Save report locally
    output_path = "rapport_premium_1xbet.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"Rapport sauvegardé sous: {output_path}")
    
    # 6. Send Email if Configured
    if SMTP_USER and SMTP_PASS:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Format HTML contents programmatically
            now_str = get_paris_time_str(fmt='%d/%m/%Y à %H:%M')
            
            # 6a. Penalty table rows
            pen_rows = ""
            if all_pen_matches:
                for m in all_pen_matches:
                    is_retained = m['pen_oui'] <= SEUIL_S8
                    pill_bg = "#f0fdf4" if is_retained else "#f8fafc"
                    pill_color = "#16a34a" if is_retained else "#64748b"
                    badge_text = "🟢 RETENU" if is_retained else "⚪ ÉLIMINÉ (> 2.90)"
                    pen_rows += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                      <td style="padding: 12px 10px; font-weight: bold; color: #475569;">{m['start_time']}</td>
                      <td style="padding: 12px 10px; color: #334155;">{m['league']}</td>
                      <td style="padding: 12px 10px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                      <td style="padding: 12px 10px; text-align: center; font-weight: bold; color: #16a34a; background-color: #f0fdf4; border-radius: 6px;">{m['pen_oui']}</td>
                      <td style="padding: 12px 10px; text-align: center; font-weight: bold; color: {pill_color}; background-color: {pill_bg}; border-radius: 6px;">{badge_text}</td>
                    </tr>
                    """
            else:
                pen_rows = "<tr><td colspan='5' style='padding: 20px; text-align: center; color: #94a3b8; font-style: italic;'>Aucun match avec marché Penalty disponible.</td></tr>"

            # 6b. Double cards
            double_cards = ""
            if combines:
                for idx, pair in enumerate(combines, 1):
                    cote_tot = round(pair[0]["pen_oui"] * pair[1]["pen_oui"], 2)
                    double_cards += f"""
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; border-left: 4px solid #1e3a8a;">
                      <div style="margin-bottom: 8px;">
                        <span style="font-weight: 800; color: #1e3a8a; font-size: 15px; text-transform: uppercase;">Combiné Double #{idx}</span>
                        <span style="float: right; background-color: #1e3a8a; color: white; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: bold;">Cote Totale: {cote_tot}</span>
                        <div style="clear: both;"></div>
                      </div>
                      <ul style="margin: 0; padding-left: 20px; color: #475569; font-size: 14px; line-height: 1.6;">
                        <li><strong>{pair[0]['start_time']}</strong> : {pair[0]['dom']} - {pair[0]['ext']} (Cote: {pair[0]['pen_oui']})</li>
                        <li><strong>{pair[1]['start_time']}</strong> : {pair[1]['dom']} - {pair[1]['ext']} (Cote: {pair[1]['pen_oui']})</li>
                      </ul>
                    </div>
                    """
            else:
                double_cards = "<p style='color: #94a3b8; font-style: italic; text-align: center; margin: 10px 0;'>Aucun combiné double disponible.</p>"

            # 6c. Strategy 3 rows
            s3_rows = ""
            if s3_matches:
                for m in s3_matches:
                    s3_rows += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                      <td style="padding: 12px 10px; font-weight: bold; color: #475569;">{m['start_time']}</td>
                      <td style="padding: 12px 10px; color: #334155;">{m['league']}</td>
                      <td style="padding: 12px 10px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                      <td style="padding: 12px 10px; text-align: center; font-weight: bold; color: #e11d48; background-color: #fff1f2; border-radius: 6px;">{m['s22']}</td>
                      <td style="padding: 12px 10px; text-align: center; color: #475569; font-weight: bold;">{m.get('over25', 'N/A')}</td>
                    </tr>
                    """
            else:
                s3_rows = "<tr><td colspan='5' style='padding: 20px; text-align: center; color: #94a3b8; font-style: italic;'>Aucun match éligible trouvé.</td></tr>"

            # 6d. Strategy 4 rows
            s4_rows = ""
            if s4_matches:
                for m in s4_matches:
                    s4_rows += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                      <td style="padding: 12px 10px; font-weight: bold; color: #475569;">{m['start_time']}</td>
                      <td style="padding: 12px 10px; color: #334155;">{m['league']}</td>
                      <td style="padding: 12px 10px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
                      <td style="padding: 12px 10px; text-align: center; font-weight: bold; color: #2563eb; background-color: #eff6ff; border-radius: 6px;">{m['over25']}</td>
                    </tr>
                    """
            else:
                s4_rows = "<tr><td colspan='4' style='padding: 20px; text-align: center; color: #94a3b8; font-style: italic;'>Aucun match éligible trouvé.</td></tr>"

            # 6e. Main Email Body HTML
            html_body = f"""
            <html>
              <head>
                <meta charset="utf-8">
              </head>
              <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 20px;">
                <div style="max-width: 650px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                  
                  <div style="text-align: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 20px; margin-bottom: 25px;">
                    <h1 style="color: #1e3a8a; margin: 0; font-size: 24px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">⚽ METRIC-FOOT PREMIUM</h1>
                    <p style="color: #64748b; margin: 5px 0 0 0; font-size: 14px; font-weight: 500;">Rapport d'analyse du {now_str}</p>
                  </div>
                  
                  <div style="color: #0f172a; font-size: 16px; font-weight: 700; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #1e3a8a; padding-left: 10px; text-transform: uppercase; letter-spacing: 0.5px;">🎯 TOUS LES MATCHS PENALTY (SEUIL SELECTION &le; {SEUIL_S8})</div>
                  <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 13px;">
                    <thead>
                      <tr style="border-bottom: 2px solid #e2e8f0;">
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569; width: 110px;">Date & Heure</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Championnat</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Match</th>
                        <th style="background-color: #f8fafc; text-align: center; padding: 10px; font-weight: 600; color: #475569; width: 85px;">Cote Pen.</th>
                        <th style="background-color: #f8fafc; text-align: center; padding: 10px; font-weight: 600; color: #475569; width: 100px;">Décision</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pen_rows}
                    </tbody>
                  </table>
                  
                  <div style="color: #0f172a; font-size: 16px; font-weight: 700; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #1e3a8a; padding-left: 10px; text-transform: uppercase; letter-spacing: 0.5px;">🔗 COMBINÉS DOUBLE DE LA SESSION (Penalty)</div>
                  {double_cards}
                  
                  <div style="color: #0f172a; font-size: 16px; font-weight: 700; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #e11d48; padding-left: 10px; text-transform: uppercase; letter-spacing: 0.5px;">🎥 STRATÉGIE 3 : OVER 2.5 YOUTUBE (Score 2-2 &le; {SEUIL_S3})</div>
                  <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 13px;">
                    <thead>
                      <tr style="border-bottom: 2px solid #e2e8f0;">
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569; width: 110px;">Date & Heure</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Championnat</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Match</th>
                        <th style="background-color: #f8fafc; text-align: center; padding: 10px; font-weight: 600; color: #475569; width: 85px;">Cote 2-2</th>
                        <th style="background-color: #f8fafc; text-align: center; padding: 10px; font-weight: 600; color: #475569; width: 85px;">Over 2.5</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s3_rows}
                    </tbody>
                  </table>
                  
                  <div style="color: #0f172a; font-size: 16px; font-weight: 700; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #2563eb; padding-left: 10px; text-transform: uppercase; letter-spacing: 0.5px;">🎯 STRATÉGIE 4 : OVER 2.5 COTE DIRECTE (Cote &le; {SEUIL_S4})</div>
                  <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 13px;">
                    <thead>
                      <tr style="border-bottom: 2px solid #e2e8f0;">
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569; width: 110px;">Date & Heure</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Championnat</th>
                        <th style="background-color: #f8fafc; text-align: left; padding: 10px; font-weight: 600; color: #475569;">Match</th>
                        <th style="background-color: #f8fafc; text-align: center; padding: 10px; font-weight: 600; color: #475569; width: 85px;">Cote O2.5</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s4_rows}
                    </tbody>
                  </table>
                  
                  <div style="text-align: center; font-size: 11px; color: #94a3b8; margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 20px; line-height: 1.5;">
                    Rapport généré automatiquement toutes les 3 heures par GitHub Actions.<br>
                    Données pré-match de l'API 1XBET (Miroir dynamique)
                  </div>
                  
                </div>
              </body>
            </html>
            """
            
            msg = MIMEMultipart()
            msg["From"] = SMTP_USER
            msg["To"] = EMAIL_TO
            msg["Subject"] = f"⚽ Rapport Premium 1XBET - {get_paris_time_str(fmt='%d/%m')}"
            msg.attach(MIMEText(html_body, "html"))
            
            with smtplib.SMTP_SSL("smtp.sfr.fr", 465) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
            print(f"E-mail envoyé avec succès à {EMAIL_TO} !")
        except Exception as e:
            print(f"Erreur d'envoi d'e-mail: {e}")

if __name__ == "__main__":
    main()
