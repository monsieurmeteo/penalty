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

    # ── Sélection S3 : Score 2-2 ≤ 12.00 (stratégie principale) ────────────
    # Niveau 1 : S3 seul     → signal YouTube (score 2-2 anormalement bas)
    # Niveau 2 : S3 + S4     → DOUBLE CONFIRMATION (score 2-2 ≤ 12 ET Over 2.5 ≤ 1.87)
    s3_matches = []
    for r in scanned_results:
        if not (r.get("s22") and r["s22"] <= SEUIL_S3):
            continue
        o25 = r.get("over25")
        double = bool(o25 and o25 <= SEUIL_S4)
        r["double_confirm"] = double
        s3_matches.append(r)

    # Trier : doubles en premier, puis par date
    s3_matches.sort(key=lambda x: (not x["double_confirm"], x.get("dt_obj", now_utc)))

    nb_double = sum(1 for m in s3_matches if m["double_confirm"])
    nb_simple = len(s3_matches) - nb_double
    print(f"S3 retenus : {len(s3_matches)} ({nb_double} double confirmation, {nb_simple} signal seul)")

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

    # ── Tableau principal S3 ─────────────────────────────────────────────────
    yt_rows = ""
    for m in s3_matches:
        s22     = m["s22"]
        s22_f   = round(s22 * 1.15, 2)
        o25     = m.get("over25")
        o25_f   = m.get("over25_fair")
        double  = m["double_confirm"]

        # ── Calcul de la mise dynamique (Gamme 3€ à 6€) ─────────────────────────
        o25_val = o25 if (o25 and o25 > 0) else 1.85
        if o25_val < 1.70:
            mise_base = 3.0
        elif 1.70 <= o25_val <= 1.89:
            mise_base = 2.5
        else:
            mise_base = 2.0

        mise = round(mise_base * 2 if double else mise_base, 2)
        mise_str = f"{mise:.2f}".replace(".00", "").replace(".", ",")

        if double:
            bg            = "#f0fdf4"
            border_color  = "#16a34a"
            decision_html = '<span style="background:#16a34a; color:white; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:bold;">⭐⭐ DOUBLE CONFIRMATION</span>'
            o25_html      = f'<br><span style="color:#15803d; font-weight:bold;">✅ O2.5: {o25}</span> <small style="color:#64748b;">(Dém. {o25_f})</small>'
        else:
            bg            = "#fefce8"
            border_color  = "#d97706"
            decision_html = '<span style="background:#d97706; color:white; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:bold;">🎥 SIGNAL S3</span>'
            o25_html      = f'<br><small style="color:#94a3b8;">O2.5: {o25 if o25 else "N/A"}</small>'

        mise_html = f'<div style="margin-top:6px; background:{border_color}; color:white; border-radius:8px; padding:4px 0; font-size:13px; font-weight:bold;">💶 {mise_str}€</div>'

        yt_rows += f"""
        <tr style="border-bottom: 2px solid {border_color}; background-color: {bg};">
          <td style="padding: 10px 8px; font-weight: bold; color: #475569; white-space:nowrap;">{m['date_str']}</td>
          <td style="padding: 10px 8px; color: #334155; font-size:12px;">{m['league']}</td>
          <td style="padding: 10px 8px; font-weight: bold; color: #0f172a; font-size:14px;">{m['dom']}<br><span style="color:#94a3b8; font-size:11px; font-weight:normal;">vs</span><br>{m['ext']}</td>
          <td style="padding: 10px 8px; text-align: center; color: #b45309;">
            Score 2-2: <b style="font-size:15px;">{s22}</b><br>
            <small style="color:#94a3b8;">(Dém. {s22_f})</small>
            {o25_html}
          </td>
          <td style="padding: 10px 8px; text-align: center;">{decision_html}{mise_html}</td>
        </tr>
        """

    if not yt_rows:
        yt_rows = '<tr><td colspan="5" style="padding:20px; text-align:center; color:#64748b; font-style:italic;">Aucun match ne valide le critère Score 2-2 &le; 12.00 dans les 48h.</td></tr>'

    # ── Corps du mail HTML ───────────────────────────────────────────────────
    html_body = f"""
    <html>
      <body style="font-family: 'Arial', sans-serif; background-color: #f1f5f9; padding: 20px;">
        <div style="max-width: 750px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">

          <!-- HEADER -->
          <div style="text-align:center; margin-bottom:20px;">
            <h1 style="color: #1e3a8a; margin:0; font-size:22px;">⚽ METRIC-FOOT — OVER 2.5</h1>
            <p style="color:#64748b; margin:6px 0 0 0; font-size:13px;">Méthode YouTube · Fenêtre 48h · {now_str}</p>
          </div>

          <!-- STATS RAPIDES -->
          <div style="display:flex; gap:10px; margin-bottom:20px; text-align:center;">
            <div style="flex:1; background:#eff6ff; border-radius:8px; padding:12px;">
              <div style="font-size:22px; font-weight:bold; color:#1d4ed8;">{len(scanned_results)}</div>
              <div style="font-size:11px; color:#64748b;">Matchs scannés</div>
            </div>
            <div style="flex:1; background:#fefce8; border-radius:8px; padding:12px;">
              <div style="font-size:22px; font-weight:bold; color:#d97706;">{nb_simple}</div>
              <div style="font-size:11px; color:#64748b;">🎥 Signal S3 seul</div>
            </div>
            <div style="flex:1; background:#f0fdf4; border-radius:8px; padding:12px;">
              <div style="font-size:22px; font-weight:bold; color:#16a34a;">{nb_double}</div>
              <div style="font-size:11px; color:#64748b;">⭐⭐ Double Confirm.</div>
            </div>
          </div>

          <!-- LÉGENDE DE GESTION DE CAPITAL (STAKING SCALE 3€ À 6€) -->
          <div style="background:#f8fafc; border-radius:8px; padding:12px 16px; margin-bottom:20px; font-size:12px; color:#475569; border:1px solid #e2e8f0;">
            <b style="color:#0f172a; font-size:13px;">📐 BARÈME DE MISES OPTIMISÉ (GAMME 3€ À 6€) :</b>
            <table style="width:100%; margin-top:6px; font-size:11px; text-align:center; border-collapse:collapse;">
              <tr style="background:#e2e8f0; font-weight:bold; color:#334155;">
                <td style="padding:4px;">Cote Over 2.5</td>
                <td style="padding:4px;">Mise Signal S3 🎥</td>
                <td style="padding:4px;">Mise Double Confirm. ⭐⭐</td>
              </tr>
              <tr>
                <td style="padding:4px; font-weight:bold; color:#16a34a;">1.50 à 1.69</td>
                <td style="padding:4px;"><b>3,00 €</b></td>
                <td style="padding:4px; color:#16a34a; font-weight:bold;">6,00 €</td>
              </tr>
              <tr style="background:#f1f5f9;">
                <td style="padding:4px; font-weight:bold; color:#2563eb;">1.70 à 1.89</td>
                <td style="padding:4px;"><b>2,50 €</b></td>
                <td style="padding:4px; color:#16a34a; font-weight:bold;">5,00 €</td>
              </tr>
              <tr>
                <td style="padding:4px; font-weight:bold; color:#d97706;">&ge; 1.90</td>
                <td style="padding:4px;"><b>2,00 €</b></td>
                <td style="padding:4px; color:#16a34a; font-weight:bold;">4,00 €</td>
              </tr>
            </table>
          </div>

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
          <!-- TABLEAU PRINCIPAL -->
          <h3 style="color: #d97706; border-bottom: 2px solid #d97706; padding-bottom: 6px; margin-top:0;">
            🎥 SÉLECTION — MÉTHODE YOUTUBE OVER 2.5
            <span style="font-size:13px; color:#64748b; font-weight:normal;">({len(s3_matches)} retenu{'s' if len(s3_matches) > 1 else ''})</span>
          </h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
              <tr style="background: #1e3a8a; color: white;">
                <th style="padding: 10px 8px; text-align: left;">Date &amp; Horaire</th>
                <th style="padding: 10px 8px; text-align: left;">Ligue</th>
                <th style="padding: 10px 8px; text-align: left;">Match</th>
                <th style="padding: 10px 8px; text-align: center;">Cotes clés</th>
                <th style="padding: 10px 8px; text-align: center;">Décision</th>
              </tr>
            </thead>
            <tbody>{yt_rows}</tbody>
          </table>

          <div style="margin-top:20px; padding:10px 14px; background:#fef9c3; border-radius:8px; font-size:11px; color:#713f12; text-align:center;">
            ⚠️ Ce rapport est généré automatiquement toutes les 2h. Pariez de manière responsable. Aucune garantie de gains.
          </div>

        </div>
      </body>
    </html>
    """

    # ── report.md ────────────────────────────────────────────────────────────
    report = [
        "# ⚽ MÉTHODE YOUTUBE OVER 2.5 — SÉLECTION 48H",
        f"**Généré le** : {now_str}  |  **Matchs scannés** : {len(scanned_results)}\n",
        f"**Total retenus** : {len(s3_matches)} ({nb_double} ⭐⭐ Double Confirmation, {nb_simple} 🎥 Signal S3)\n",
        "| Décision | Date | Ligue | Match | Score 2-2 | Over 2.5 |",
        "| :---: | :---: | :--- | :--- | :---: | :---: |",
    ]
    for m in s3_matches:
        badge = "⭐⭐ DOUBLE" if m["double_confirm"] else "🎥 S3"
        o25 = m.get("over25", "N/A")
        report.append(f"| {badge} | {m['date_str']} | {m['league']} | **{m['dom']} vs {m['ext']}** | **{m['s22']}** | {o25} |")

    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    # ── Envoi Gmail SMTP ─────────────────────────────────────────────────────
    recipients     = [r.strip() for r in os.environ.get("EMAIL_TO", "gregory.langlet@sfr.fr, langlet.gregory@gmail.com").split(",") if r.strip()]
    gmail_email    = os.environ.get("GMAIL_EMAIL", "langlet.gregory@gmail.com")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    nb_s3 = len(s3_matches)
    subject_flag = f"🔥 {nb_double} DOUBLE + {nb_simple} S3" if nb_double else (f"🎥 {nb_s3} S3 détecté{'s' if nb_s3>1 else ''}" if nb_s3 else "ℹ️ Aucun signal")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"OVER 2.5 UNIBET — {subject_flag} — {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC"
    msg["From"]    = f"Gregory LANGLET <{gmail_email if gmail_password else 'gregory.langlet@sfr.fr'}>"
    msg["To"]      = ", ".join(recipients)
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
