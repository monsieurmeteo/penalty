import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Seuils ──────────────────────────────────────────────────────────────────
SEUIL_S4  = 1.87   # Over 2.5 direct Unibet  (cote juste 1.75 × marge 1.07)
SEUIL_S3  = 12.00  # Score exact 2-2 Unibet  (1XBET ≤ 10.00 × ratio 1.115)

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

        c1 = cx = c2 = over25 = under25 = s22 = None
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
            }
    except Exception:
        return None
    return None

def main():
    print("=== AUTOMATISATION UNIBET OVER 2.5 (FENÊTRE 48H) ===")
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

    # ── Stratégies retenues ──────────────────────────────────────────────────
    s4_matches  = [r for r in scanned_results if r.get("over25") and r["over25"] <= SEUIL_S4]
    s3_matches  = [r for r in scanned_results if r.get("s22") and r["s22"] <= SEUIL_S3]

    # ── Évolutions Over 2.5 vs run précédent ────────────────────────────────
    history_file = "previous_odds.json"
    prev_state = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                prev_state = json.load(f)
        except Exception:
            pass

    curr_state = {
        "o25": {m["id"]: {"match": f"{m['dom']} - {m['ext']}", "league": m["league"],
                           "date_str": m["date_str"], "val": m["over25"], "fair": m["over25_fair"]}
                for m in s4_matches},
        "s3":  {m["id"]: {"match": f"{m['dom']} - {m['ext']}", "league": m["league"],
                           "date_str": m["date_str"], "val": m["s22"], "over25": m.get("over25")}
                for m in s3_matches},
    }

    prev_o25 = prev_state.get("o25", {})
    new_o25  = [v for k, v in curr_state["o25"].items() if k not in prev_o25]
    drop_o25 = [v for k, v in prev_o25.items() if k not in curr_state["o25"]]
    var_o25  = []
    for k, v in curr_state["o25"].items():
        if k in prev_o25:
            old_val = prev_o25[k].get("val")
            if old_val and old_val != v["val"]:
                diff = round(v["val"] - old_val, 2)
                var_o25.append({**v, "old_val": old_val, "diff": diff})

    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(curr_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')

    # ── Bloc Évolutions HTML ─────────────────────────────────────────────────
    evo_html = ""
    if new_o25 or var_o25 or drop_o25:
        evo_html += '<div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:15px; margin-bottom:25px;">'
        evo_html += '<h3 style="color:#0f172a; margin-top:0; border-bottom:1px solid #cbd5e1; padding-bottom:5px;">📊 ÉVOLUTIONS DEPUIS LE DERNIER RUN (~2h)</h3>'

        if new_o25:
            evo_html += '<p style="color:#16a34a; font-weight:bold; margin-bottom:5px;">🆕 Nouveaux matchs Over 2.5 :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in new_o25:
                evo_html += f"<li><b>{item['date_str']}</b> | {item['league']} : <b>{item['match']}</b> (Cote O2.5: <b>{item['val']}</b>)</li>"
            evo_html += '</ul>'

        if var_o25:
            evo_html += '<p style="color:#2563eb; font-weight:bold; margin-bottom:5px;">📈📉 Variations de cotes Over 2.5 :</p><ul style="margin:0 0 10px 0; font-size:13px;">'
            for item in var_o25:
                arrow = "🔺" if item["diff"] > 0 else "🔻"
                evo_html += f"<li><b>{item['match']}</b> : {item['old_val']} &rarr; <b>{item['val']}</b> ({arrow} {item['diff']:+0.2f})</li>"
            evo_html += '</ul>'

        if drop_o25:
            evo_html += '<p style="color:#dc2626; font-weight:bold; margin-bottom:5px;">❌ Matchs retirés (seuil dépassé) :</p><ul style="margin:0 0 5px 0; font-size:13px;">'
            for item in drop_o25:
                evo_html += f"<li><b>{item['match']}</b> ({item['league']})</li>"
            evo_html += '</ul>'

        evo_html += '</div>'
    else:
        evo_html = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px; margin-bottom:20px; text-align:center; color:#64748b; font-size:13px;">ℹ️ Aucune variation majeure depuis le dernier run.</div>'

    # ── Tableau S4 Over 2.5 ──────────────────────────────────────────────────
    o25_rows = ""
    for m in s4_matches:
        o25_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #eff6ff;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{m['date_str']}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #2563eb;"><b>{m['over25']}</b> <br><small style="color:#64748b;">(Dém. {m['over25_fair']})</small></td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #2563eb;">🟢 RETENU</td>
        </tr>
        """
    if not o25_rows:
        o25_rows = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide le critère Over 2.5 &le; 1.87 dans les 48h.</td></tr>'

    # ── Tableau S3 YouTube Score 2-2 ─────────────────────────────────────────
    yt_rows = ""
    for m in s3_matches:
        s22 = m['s22']
        s22_f = round(s22 * 1.15, 2)
        o25 = m.get('over25')
        o25_fair = m.get('over25_fair')
        o25_d = f"O2.5: <b>{o25}</b> <small>(Dém. {o25_fair})</small>" if o25 else "O2.5: N/A"
        yt_rows += f"""
        <tr style="border-bottom: 1px solid #e2e8f0; background-color: #fefce8;">
          <td style="padding: 8px; font-weight: bold; color: #475569;">{m['date_str']}</td>
          <td style="padding: 8px; color: #334155;">{m['league']}</td>
          <td style="padding: 8px; font-weight: bold; color: #0f172a;">{m['dom']} - {m['ext']}</td>
          <td style="padding: 8px; text-align: center; color: #b45309;">2-2: <b>{s22}</b> <small>(Dém. {s22_f})</small><br>{o25_d}</td>
          <td style="padding: 8px; text-align: center; font-weight: bold; color: #d97706;">🟢 RETENU S3</td>
        </tr>
        """
    if not yt_rows:
        yt_rows = '<tr><td colspan="5" style="padding:15px; text-align:center; color:#64748b;">Aucun match ne valide le critère Score 2-2 &le; 12.00 dans les 48h.</td></tr>'

    # ── Corps du mail HTML ───────────────────────────────────────────────────
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 20px;">
        <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 10px; border: 1px solid #e2e8f0;">
          <h1 style="color: #1e3a8a; text-align: center;">⚽ METRIC-FOOT — OVER 2.5 (48H)</h1>
          <p style="text-align: center; color: #64748b;">{len(scanned_results)} matchs scannés — Fenêtre 48h — {now_str}</p>

          {evo_html}

          <h3 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 5px;">⚡ AUDIT OVER 2.5 RETENUS (SEUIL UNIBET &le; 1.87)</h3>
          <p style="font-size:12px; color:#64748b; margin-top:-5px;">
            Cote juste estimée 1.75 × marge Unibet 1.07 = <b>1.87</b> &nbsp;|&nbsp;
            Probabilité implicite : {round(1/SEUIL_S4*100,1)}%
          </p>
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

          <h3 style="color: #d97706; border-bottom: 2px solid #d97706; padding-bottom: 5px; margin-top: 30px;">🎥 MÉTHODE YOUTUBE — SCORE 2-2 &le; 12.00 (signal Over 2.5)</h3>
          <p style="font-size:12px; color:#64748b; margin-top:-5px;">
            Transposé depuis 1XBET ≤ 10.00 (ratio Unibet/1XBET = 1.115) &nbsp;|&nbsp;
            Probabilité implicite 2-2 : {round(1/SEUIL_S3*100,1)}% (≥ 2× la normale)
          </p>
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

          <div style="margin-top:25px; padding:12px; background:#f0f9ff; border-radius:8px; font-size:12px; color:#475569;">
            <b>📐 Rappel calibrage :</b>
            S4 Over 2.5 ≤ <b>1.87</b> (Unibet ARJEL) &nbsp;|&nbsp;
            S3 Score 2-2 ≤ <b>12.00</b> Unibet = ≤ <b>10.00</b> 1XBET
          </div>
        </div>
      </body>
    </html>
    """

    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ OVER 2.5 — SÉLECTION 48H UNIBET",
        f"**Généré le** : {now_str}\n",
        "## ⚡ OVER 2.5 RETENUS (S4 — cote ≤ 1.87)",
        "| Date & Horaire | Ligue | Match | Cote Brute | Cote Démargée |",
        "| :---: | :--- | :--- | :---: | :---: |",
    ]
    for m in s4_matches:
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['over25']}** | **{m['over25_fair']}** |")

    report += [
        "\n## 🎥 MÉTHODE YOUTUBE — SCORE 2-2 ≤ 12.00 (S3)",
        "| Date & Horaire | Ligue | Match | Score 2-2 | Over 2.5 |",
        "| :---: | :--- | :--- | :---: | :---: |",
    ]
    for m in s3_matches:
        o25 = m.get('over25', 'N/A')
        report.append(f"| {m['date_str']} | {m['league']} | {m['dom']} vs {m['ext']} | **{m['s22']}** | {o25} |")

    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    # ── Envoi Gmail SMTP ─────────────────────────────────────────────────────
    recipients = [r.strip() for r in os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr, langlet.gregory@gmail.com").split(",") if r.strip()]
    gmail_email = os.environ.get("GMAIL_EMAIL", "langlet.gregory@gmail.com")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"OVER 2.5 UNIBET (48H) — {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
    msg["From"] = f"Gregory LANGLET <{gmail_email if gmail_password else 'gregory.langlet@sfr.fr'}>"
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
