import os, sys, json, time, re, urllib.request
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

sys.path.append(r"C:\Users\grego\Documents\DEV_DIVERS\penalty")
from scripts.auto_premium_unibet import get_unibet_active_games, scan_unibet_match_details

SEUIL_S3 = 12.00
MIN_O25  = 1.55
MAX_O25  = 1.70

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def normalize(name: str) -> str:
    name = re.sub(r'\s+(FC|SC|CF|AS|AC|1\.|FK|BK|SK|IF|IK|GF|FF|VPS|Utd|United|City|Town|Club|Sporting|Real)\b', '', name, flags=re.IGNORECASE)
    return name.strip().lower()

def fetch_live_scores_espn() -> list:
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?limit=300"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [ESPN] Erreur: {e}")
        return []

    live = []
    for ev in data.get("events", []):
        state = ev.get("status", {}).get("type", {}).get("state", "")
        if state != "in":
            continue

        comps = ev.get("competitions", [{}])[0]
        teams = comps.get("competitors", [])
        home = next((t for t in teams if t.get("homeAway") == "home"), {})
        away = next((t for t in teams if t.get("homeAway") == "away"), {})

        h_name  = home.get("team", {}).get("displayName", "")
        a_name  = away.get("team", {}).get("displayName", "")
        h_score = int(home.get("score", 0) or 0)
        a_score = int(away.get("score", 0) or 0)
        clock   = ev.get("status", {}).get("displayClock", "0:00")
        try:
            minute = str(int(clock.split(":")[0])) + "'"
        except Exception:
            minute = clock + "'"

        period = ev.get("status", {}).get("type", {}).get("shortDetail", "")
        if "mi-temps" in period.lower() or "halftime" in period.lower() or "HT" in period:
            period_label = "Mi-Temps"
        elif "1" in period and ("mi" in period.lower() or "half" in period.lower()):
            period_label = "1ère Mi-Temps"
        else:
            period_label = "2ème Mi-Temps"

        league_name = ev.get("name", "")
        live.append({
            "espn_id": str(ev.get("id", "")),
            "home": h_name,
            "away": a_name,
            "score_dom": h_score,
            "score_ext": a_score,
            "minute": minute,
            "period_label": period_label,
            "league_raw": league_name,
        })

    print(f"  [ESPN] {len(live)} matchs en direct récupérés de l'API officielle.")
    return live

def match_unibet_to_espn(unibet_matches: list, espn_live: list) -> list:
    """
    Croise STRICTEMENT les matchs Unibet scannés avec les vrais scores ESPN en direct.
    Similarité minimale requise >= 0.75 pour éviter tout faux positif.
    """
    live_enriched = []
    
    for um in unibet_matches:
        dom = um.get("dom", "")
        ext = um.get("ext", "")

        best_score = 0.0
        best_espn = None

        for es in espn_live:
            s1 = similarity(normalize(dom), normalize(es["home"]))
            s2 = similarity(normalize(ext), normalize(es["away"]))
            combined = (s1 + s2) / 2.0
            if combined > best_score:
                best_score = combined
                best_espn = es

        # Exigence stricte >= 0.75 de similarité
        if best_espn and best_score >= 0.75:
            print(f"  🎯 MATCH LIVE EXACT : {dom} vs {ext} → {best_espn['home']} {best_espn['score_dom']}-{best_espn['score_ext']} {best_espn['away']} ({best_espn['minute']})")
            buts = (best_espn["score_dom"] or 0) + (best_espn["score_ext"] or 0)
            o25 = um.get("over25")
            sel_status = "WON" if buts >= 3 else "PENDING"

            live_enriched.append({
                "id": "live-" + best_espn["espn_id"],
                "dom": dom,
                "ext": ext,
                "league": um.get("league", best_espn["league_raw"]),
                "start_iso": um.get("start_iso"),
                "date_str": "En Direct",
                "status": "LIVE",
                "score_dom": best_espn["score_dom"],
                "score_ext": best_espn["score_ext"],
                "minute": best_espn["minute"],
                "period_label": best_espn["period_label"],
                "is_selected": um.get("is_selected", False),
                "selection_status": sel_status,
                "rejection_reason": um.get("rejection_reason"),
                "s22": um.get("s22"),
                "over25": o25,
                "buteur_name": um.get("buteur_name"),
                "buteur_cote": um.get("buteur_cote"),
                "profit_units": round(o25 - 1.0, 2) if sel_status == "WON" and o25 else 0.0
            })

    return live_enriched

def load_real_history():
    """Charge l'historique réel conservé dans previous_odds.json (aucun résultat inventé)."""
    history_file = r"C:\Users\grego\Documents\DEV_DIVERS\penalty\previous_odds.json"
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("history_matches", [])
        except Exception:
            pass
    return []

def main():
    print("=== OVER 2.5 DASHBOARD — SYNCHRONISATION 100% REELLE & VERIFIEE ===")
    
    # 1. Scraping Unibet fixtures (48h)
    print("\n[1/3] Scraping en direct Unibet France...")
    active_games = get_unibet_active_games()
    scanned_all = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in active_games]
        for f in as_completed(futs):
            res = f.result()
            if res: scanned_all.append(res)
    
    # 2. Classification et application des règles Over 2.5 + Score 2-2
    print(f"\n[2/3] Analyse des {len(scanned_all)} matchs Unibet...")
    upcoming_matches = []
    for m in scanned_all:
        s22 = m.get("s22")
        o25 = m.get("over25")
        is_selected = bool(s22 and s22 <= SEUIL_S3 and o25 and MIN_O25 <= o25 <= MAX_O25)
        rejection = None
        if not is_selected:
            reasons = []
            if s22 is None: reasons.append("Score 2-2 N/D")
            elif s22 > SEUIL_S3: reasons.append(f"Score 2-2 = {s22:.2f} (> 12.00)")
            if o25 is None: reasons.append("Over 2.5 N/D")
            elif o25 < MIN_O25: reasons.append(f"Over 2.5 = {o25:.2f} (< 1.55)")
            elif o25 > MAX_O25: reasons.append(f"Over 2.5 = {o25:.2f} (> 1.70)")
            rejection = " • ".join(reasons) if reasons else "Critères non atteints"
            
        upcoming_matches.append({
            "id": str(m.get("id")),
            "dom": m.get("dom"), "ext": m.get("ext"), "league": m.get("league", "Football"),
            "start_iso": m.get("start_iso"), "date_str": m.get("date_str", "À venir"),
            "status": "UPCOMING", "score_dom": None, "score_ext": None,
            "is_selected": is_selected, "selection_status": "PENDING",
            "rejection_reason": rejection, "s22": s22, "over25": o25,
            "buteur_name": m.get("buteur_name"), "buteur_cote": m.get("buteur_cote"),
            "profit_units": 0.0
        })

    # 3. Croisement direct et strict avec ESPN Live API
    print("\n[3/3] Contrôle des matchs en direct sur l'API ESPN...")
    espn_live = fetch_live_scores_espn()
    live_matches = match_unibet_to_espn(upcoming_matches, espn_live)
    
    # Retirer des prochains matchs ceux qui sont actuellement en direct
    live_ids = {m["id"].replace("live-", "") for m in live_matches}
    upcoming_matches = [m for m in upcoming_matches if str(m.get("id")) not in live_ids]
    
    # 4. Charger l'historique réel (aucun hasard / aucune simulation)
    history_matches = load_real_history()
    
    # ── CALCUL DES KPIs & BANKROLL ──
    selected_finished = [m for m in history_matches if m.get("is_selected")]
    selected_finished.sort(key=lambda x: x.get("start_iso", ""))
    
    cumul_profit, wins, losses = 0.0, 0, 0
    current_br = 100.0
    bankroll_curve = []
    
    for idx, m in enumerate(selected_finished):
        p = m.get("profit_units", 0.0)
        if m.get("selection_status") == "WON":
            wins += 1; cumul_profit += p; current_br += p
        else:
            losses += 1; cumul_profit += p; current_br += p
        bankroll_curve.append({
            "step": idx + 1,
            "date": m.get("date_str", "").split(" à ")[0],
            "match": f"{m.get('dom')} vs {m.get('ext')}",
            "profit_cumul": round(cumul_profit, 2),
            "bankroll": round(current_br, 2),
            "result": m.get("selection_status")
        })
    
    total_staked = len(selected_finished) * 1.0
    win_rate = round((wins / len(selected_finished)) * 100, 1) if selected_finished else 0.0
    roi_pct = round((cumul_profit / total_staked) * 100, 1) if total_staked > 0 else 0.0
    
    # ── REPARTITION PAR LIGUE ──
    league_dict = {}
    for m in selected_finished:
        lg = m.get("league", "Football")
        if lg not in league_dict:
            league_dict[lg] = {"total": 0, "won": 0, "lost": 0, "profit": 0.0}
        league_dict[lg]["total"] += 1
        if m.get("selection_status") == "WON":
            league_dict[lg]["won"] += 1; league_dict[lg]["profit"] += m.get("profit_units", 0.0)
        else:
            league_dict[lg]["lost"] += 1; league_dict[lg]["profit"] += m.get("profit_units", 0.0)
    
    league_stats = sorted([{
        "league": lg,
        "total": v["total"], "won": v["won"], "lost": v["lost"],
        "win_rate": round((v["won"] / v["total"]) * 100, 1) if v["total"] else 0.0,
        "profit": round(v["profit"], 2),
        "roi": round((v["profit"] / v["total"]) * 100, 1) if v["total"] else 0.0,
    } for lg, v in league_dict.items()], key=lambda x: x["total"], reverse=True)
    
    all_o25 = [m["over25"] for m in upcoming_matches if m.get("over25")]
    all_s22 = [m["s22"] for m in upcoming_matches if m.get("s22")]
    
    summary = {
        "total_live": len(live_matches),
        "total_scanned_upcoming": len(upcoming_matches),
        "total_selected_upcoming": len([m for m in upcoming_matches if m["is_selected"]]),
        "total_history_bets": len(selected_finished),
        "total_wins": wins, "total_losses": losses,
        "win_rate_over25": win_rate,
        "total_profit_units": round(cumul_profit, 2),
        "roi_pct": roi_pct,
        "initial_bankroll": 100.0,
        "current_bankroll": round(current_br, 2),
        "avg_odds_over25_global": round(sum(all_o25)/len(all_o25), 2) if all_o25 else 0.0,
        "avg_odds_s22_global": round(sum(all_s22)/len(all_s22), 2) if all_s22 else 0.0,
        "last_update": datetime.now(timezone.utc).isoformat()
    }
    
    final_output = {
        "summary": summary,
        "bankroll_curve": bankroll_curve,
        "league_stats": league_stats,
        "matches": live_matches + upcoming_matches + history_matches
    }
    
    target = r"C:\Users\grego\Documents\DEV_DIVERS\penalty\dashboard\public\data\matches.json"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ DATASET 100% REEL GENERE SANS SIMULATION : {target}")
    print(f"   🔴 En direct réels (correspondance stricte ≥ 75%) : {len(live_matches)}")
    print(f"   📅 Matchs Unibet réels à venir (48h)              : {len(upcoming_matches)}")
    print(f"   📜 Historique réel enregistré                       : {len(history_matches)}")

if __name__ == "__main__":
    main()
