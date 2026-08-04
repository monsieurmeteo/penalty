import os, sys, time, json, re, smtplib, unicodedata, requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Seuils ──────────────────────────────────────────────────────────────────
SEUIL_S4      = 1.87   # Over 2.5 direct Unibet  (cote juste 1.75 × marge 1.07)
SEUIL_S3      = 12.00  # Score exact 2-2 Unibet  (1XBET ≤ 10.00 × ratio 1.115)
MIN_COTE_O25  = 1.50   # Cote Over 2.5 minimale retenue (filtre anti-piège < 1.50)

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
        # Filtre anti-piège : exclure si cote Over 2.5 < 1.50 (mauvais rapport risque/gain)
        if o25 and o25 < MIN_COTE_O25:
            continue
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

    # ── Génération des cartes de matchs ──────────────────────────────────────
    yt_cards = ""
    for m in s3_matches:
        s22 = m["s22"]
        o25 = m.get("over25")
        o25_f = m.get("over25_fair")
        double = m["double_confirm"]

        # ── Calcul de la mise dynamique (Chiffres ronds sans décimales) ─────────
        o25_val = o25 if (o25 and o25 > 0) else 1.85
        if o25_val < 1.70:
            mise_base = 3
        elif 1.70 <= o25_val <= 1.89:
            mise_base = 2
        else:
            mise_base = 1

        mise = mise_base * 2 if double else mise_base

        if double:
            card_bg       = "#f0fdf4"
            card_border   = "#22c55e"
            badge_bg      = "#15803d"
            badge_text    = "⭐⭐ DOUBLE CONFIRMATION"
            o25_badge     = f'<span style="background:#dcfce7; color:#15803d; padding:4px 8px; border-radius:6px; font-weight:bold; font-size:12px; display:inline-block;">✅ Over 2.5: <b>{o25}</b> <small style="color:#64748b;">(Dém. {o25_f})</small></span>'
            btn_bg        = "#15803d"
        else:
            card_bg       = "#fffbeb"
            card_border   = "#f59e0b"
            badge_bg      = "#b45309"
            badge_text    = "🎥 SIGNAL S3 (MÉTHODE YOUTUBE)"
            o25_badge     = f'<span style="background:#fef3c7; color:#92400e; padding:4px 8px; border-radius:6px; font-size:12px; display:inline-block;">Over 2.5: <b>{o25 if o25 else "N/A"}</b></span>'
            btn_bg        = "#d97706"

        yt_cards += f"""
        <div style="background:{card_bg}; border:2px solid {card_border}; border-radius:12px; padding:18px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">

          <!-- LIGNE HAUT : DATETIME & BADGE STRATEGIE -->
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid rgba(0,0,0,0.06); padding-bottom:8px;">
            <div style="font-size:12px; font-weight:bold; color:#475569;">
              📅 {m['date_str']} &nbsp;|&nbsp; <span style="color:#64748b; font-weight:normal;">{m['league']}</span>
            </div>
            <div style="background:{badge_bg}; color:white; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:bold; letter-spacing:0.3px;">
              {badge_text}
            </div>
          </div>

          <!-- LIGNE MILIEU : AFFICHAGE DU MATCH -->
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px;">
            <div style="flex:1;">
              <div style="font-size:17px; font-weight:800; color:#0f172a; line-height:1.3;">
                {m['dom']} <span style="color:#94a3b8; font-weight:400; font-size:14px;">vs</span> {m['ext']}
              </div>
            </div>
          </div>

          <!-- LIGNE BAS : COTES ET BOUTON MISE -->
          <div style="display:flex; align-items:center; justify-content:space-between; background:rgba(255,255,255,0.7); padding:10px 14px; border-radius:8px; border:1px solid rgba(0,0,0,0.05);">
            <div style="font-size:13px; color:#334155;">
              <span style="background:#e2e8f0; color:#1e293b; padding:4px 8px; border-radius:6px; font-weight:bold; font-size:12px; margin-right:6px; display:inline-block;">
                Score 2-2: <b style="color:#0f172a; font-size:14px;">{s22}</b>
              </span>
              {o25_badge}
            </div>
            <div style="background:{btn_bg}; color:white; padding:8px 16px; border-radius:8px; font-size:14px; font-weight:800; letter-spacing:0.5px; text-align:center; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
              💶 MISER {mise} €
            </div>
          </div>

        </div>
        """

    if not yt_cards:
        yt_cards = '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:24px; text-align:center; color:#64748b; font-style:italic;">Aucun match ne valide le critère Score 2-2 &le; 12.00 dans les 48h.</div>'

    # ── Section Duos Bar Tabac (3 Tickets à 3€ par Duo) ──────────────────────
    tabac_duo_html = ""
    doubles_list = [m for m in s3_matches if m["double_confirm"]]
    duo_cards = []
    
    for idx in range(0, len(doubles_list) - 1, 2):
        duo_num = (idx // 2) + 1
        mA = doubles_list[idx]
        mB = doubles_list[idx + 1]
        cA = mA.get("over25", 1.75)
        cB = mB.get("over25", 1.80)
        cComb = round(cA * cB, 2)
        pay1 = round(3.0 * cA, 2)
        pay2 = round(3.0 * cB, 2)
        payComb = round(3.0 * cComb, 2)
        totMax = round(pay1 + pay2 + payComb, 2)
        profMax = round(totMax - 9.0, 2)
        perte1 = round(9.0 - pay1, 2)

        card = f"""
        <div style="background:linear-gradient(135deg, #065f46 0%, #047857 100%); border-radius:12px; padding:18px; margin-bottom:16px; color:white; box-shadow:0 4px 12px rgba(4,120,87,0.15);">
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.2); padding-bottom:8px; margin-bottom:12px;">
            <div style="font-weight:800; font-size:15px; letter-spacing:0.5px;">🎟️ DUO BAR TABAC N°{duo_num} (3 TICKETS À 3€)</div>
            <div style="background:rgba(255,255,255,0.2); padding:2px 8px; border-radius:12px; font-size:11px; font-weight:bold;">BUDGET DUO : 9,00 €</div>
          </div>
          
          <div style="font-size:13px; margin-bottom:10px; line-height:1.5;">
            <b>Match 1 :</b> {mA['dom']} vs {mA['ext']} &nbsp;|&nbsp; <span style="background:rgba(255,255,255,0.2); padding:1px 6px; border-radius:4px;">Cote Over 2.5 : {cA}</span><br>
            <b>Match 2 :</b> {mB['dom']} vs {mB['ext']} &nbsp;|&nbsp; <span style="background:rgba(255,255,255,0.2); padding:1px 6px; border-radius:4px;">Cote Over 2.5 : {cB}</span>
          </div>

          <div style="background:rgba(0,0,0,0.2); padding:10px 14px; border-radius:8px; font-size:12px; margin-bottom:12px; line-height:1.6;">
            <b>• Ticket 1 (Simple 1) :</b> 3,00 € &rarr; Gain potentiel : <b>{pay1} €</b><br>
            <b>• Ticket 2 (Simple 2) :</b> 3,00 € &rarr; Gain potentiel : <b>{pay2} €</b><br>
            <b>• Ticket 3 (Combiné 1+2) :</b> 3,00 € (Cote {cComb}) &rarr; Gain potentiel : <b>{payComb} €</b>
          </div>

          <div style="font-size:12px; display:flex; gap:10px;">
            <div style="flex:1; background:rgba(255,255,255,0.15); padding:8px 12px; border-radius:6px; text-align:center;">
              🟢 <b>SI 2/2 PASSE :</b><br>Vous touchez <b style="font-size:15px; color:#fef08a;">{totMax} € CASH</b><br>(+{profMax} € net)
            </div>
            <div style="flex:1; background:rgba(255,255,255,0.15); padding:8px 12px; border-radius:6px; text-align:center;">
              🟡 <b>SI 1/2 PASSE :</b><br>Vous touchez <b style="font-size:15px; color:#ffffff;">{pay1} € CASH</b><br>(perte amortie -{perte1} €)
            </div>
          </div>
        </div>
        """
        duo_cards.append(card)

    if duo_cards:
        tabac_duo_html = f"""
        <div style="margin-bottom:24px;">
          <h3 style="color: #0f172a; margin:0 0 12px 0; font-size:16px; font-weight:800; text-transform:uppercase; letter-spacing:0.5px;">
            🔥 DUOS CONSEILLÉS BAR TABAC ({len(duo_cards)} DUO{'S' if len(duo_cards)>1 else ''})
          </h3>
          {''.join(duo_cards)}
        </div>
        """

    # ── Corps du mail HTML ───────────────────────────────────────────────────
    html_body = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
      </head>
      <body style="font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin:0; padding: 20px;">
        <div style="max-width: 680px; margin: 0 auto; background: #ffffff; padding: 28px; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 4px 16px rgba(0,0,0,0.05);">

          <!-- BANNIÈRE HEADER ELEGANTE -->
          <div style="background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); border-radius: 12px; padding: 22px; text-align: center; margin-bottom: 24px; color: white;">
            <h1 style="margin: 0; font-size: 24px; font-weight: 800; letter-spacing: 0.5px; color: #ffffff;">⚽ METRIC-FOOT — OVER 2.5</h1>
            <p style="margin: 6px 0 0 0; font-size: 13px; color: #93c5fd;">Méthode YouTube (Signal Score 2-2 &le; 12.00) · Fenêtre 48h</p>
            <div style="margin-top: 10px; display: inline-block; background: rgba(255,255,255,0.15); padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;">
              Mise à jour : {now_str}
            </div>
          </div>

          <!-- KPI BLOCS SYNTHÈSE -->
          <table style="width:100%; border-collapse:separate; border-spacing:10px; margin-bottom:20px; text-align:center;">
            <tr>
              <td style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; width:33%;">
                <div style="font-size:26px; font-weight:800; color:#1e40af;">{len(scanned_results)}</div>
                <div style="font-size:11px; font-weight:600; color:#64748b; text-transform:uppercase; margin-top:2px;">Matchs scannés</div>
              </td>
              <td style="background:#fffbeb; border:1px solid #fef08a; border-radius:10px; padding:14px; width:33%;">
                <div style="font-size:26px; font-weight:800; color:#b45309;">{nb_simple}</div>
                <div style="font-size:11px; font-weight:600; color:#854d0e; text-transform:uppercase; margin-top:2px;">🎥 Signal S3 Seul</div>
              </td>
              <td style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:14px; width:33%;">
                <div style="font-size:26px; font-weight:800; color:#15803d;">{nb_double}</div>
                <div style="font-size:11px; font-weight:600; color:#166534; text-transform:uppercase; margin-top:2px;">⭐⭐ Double Confirm.</div>
              </td>
            </tr>
          </table>

          <!-- CARTE SPECIALE DUO CONSEILLE BAR TABAC -->
          {tabac_duo_html}

          <!-- SECTION ÉVOLUTIONS -->
          {evo_html}

          <!-- SECTION CARTES MATCHS -->
          <div style="margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
            <h3 style="color: #0f172a; margin:0; font-size:16px; font-weight:800; text-transform:uppercase; letter-spacing:0.5px;">
              🎥 SÉLECTION MATCHS ({len(s3_matches)})
            </h3>
            <span style="font-size:12px; color:#64748b;">Trié par niveau de confiance</span>
          </div>

          <!-- LISTE DES CARTES DE MATCHS -->
          {yt_cards}

          <!-- FOOTER -->
          <div style="margin-top:28px; padding:12px 16px; background:#fef9c3; border-radius:10px; font-size:11px; color:#713f12; text-align:center; border:1px solid #fef08a;">
            ⚠️ Rapport automatisé Unibet France (48h). Les paris sportifs comportent des risques. Jouez avec modération.
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
