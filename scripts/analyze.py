# ==============================================================================
# ANALYZE.PY V13 — AFFICHAGE OBLIGATOIRE DES 10 DERNIERS SCORES REELS (DOM & EXT)
# ==============================================================================

import sys, os, requests, json, unicodedata, re
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.adamchoi.co.uk"
BASE_WIDGET = "https://api.choistats.com/api/widget"

HEADERS = {
    "Authorization-Client": "ADAMCHOI.CO.UK",
    "Referer": "https://www.adamchoi.co.uk/",
    "User-Agent": "Mozilla/5.0"
}
WIDGET_HEADERS = {
    "X-AdamChoi-Api-Token": "45834886-68b3-11eb-99f4-9e36325824ad",
    "Referer": "https://www.adamchoi.co.uk/",
    "User-Agent": "Mozilla/5.0"
}

def clean_str(s):
    if not s: return ""
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')
    s = s.lower().replace("-", " ").replace(".", " ").replace("_", " ")
    for strip_word in ["fc", "bk", "if", "sc", "ac", "fk", "cd", "sk", "cf", "sv", "v", "vs", "contre", "pec"]:
        s = f" {s} ".replace(f" {strip_word} ", " ").strip()
    return s

def similarity(a, b):
    a_c = clean_str(a)
    b_c = clean_str(b)
    if a_c in b_c or b_c in a_c:
        return 0.95
    return SequenceMatcher(None, a_c, b_c).ratio()

def fetch(url, headers=HEADERS):
    try:
        r = requests.get(url, headers=headers, timeout=8)
        res = r.json() if r.status_code == 200 else {}
        return res if isinstance(res, (dict, list)) else {}
    except Exception:
        return {}

def find_fixture_fuzzy(home_query, away_query, fixtures_data=None):
    if not fixtures_data or not isinstance(fixtures_data, dict):
        fixtures_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
    
    best_match = None
    best_score = 0.0

    if isinstance(fixtures_data, dict):
        for d in fixtures_data.get("dates", []):
            for lg in d.get("leagues", []):
                for fx in lg.get("fixtures", []):
                    h_name = fx.get("hometeam", "")
                    a_name = fx.get("awayteam", "")
                    
                    score_h = similarity(home_query, h_name)
                    score_a = similarity(away_query, a_name)
                    combined = (score_h + score_a) / 2.0

                    if combined > best_score:
                        best_score = combined
                        best_match = (fx.get("externalId"), h_name, a_name, lg.get("league"))

    if best_match and best_score >= 0.40:
        return best_match
    
    return "19635927", home_query, away_query, "SA1"

def analyze_pure_stats_20(home_query, away_query, fixtures_data=None, is_batch=False):
    ext_id, team_a, team_b, league = find_fixture_fuzzy(home_query, away_query, fixtures_data)

    if not is_batch:
        print(f"🔍 ÉQUIPES DÉTECTÉES : '{team_a}' vs '{team_b}' ({league})\n")

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_comp = ex.submit(fetch, f"{BASE}/scripts/data/json/scripts/pages/comparison/getComparisonStatsAsJson.php?clflc=abc&hometeam={team_a}&awayteam={team_b}&hometeamleague={league}&awayteamleague={league}&numrecentmatches=20")
        f_avg  = ex.submit(fetch, f"{BASE_WIDGET}/match/{ext_id}/team-averages?clflc=abc&token=45834886-68b3-11eb-99f4-9e36325824ad", WIDGET_HEADERS)
        f_res  = ex.submit(fetch, f"{BASE_WIDGET}/match/{ext_id}/recent-results?clflc=abc&token=45834886-68b3-11eb-99f4-9e36325824ad", WIDGET_HEADERS)

        comp = f_comp.result()
        w_avg = f_avg.result()
        w_res = f_res.result()

    if not isinstance(comp, dict): comp = {}
    if not isinstance(w_avg, dict): w_avg = {}
    if not isinstance(w_res, dict): w_res = {}

    recent_h_all = comp.get("recentmatches", {}).get("homeall", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_a_all = comp.get("recentmatches", {}).get("awayall", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_h_dom = comp.get("recentmatches", {}).get("homehome", []) if isinstance(comp.get("recentmatches"), dict) else []
    recent_a_ext = comp.get("recentmatches", {}).get("awayaway", []) if isinstance(comp.get("recentmatches"), dict) else []

    if not recent_h_dom: recent_h_dom = w_res.get("recentHomeHomeResults", [])
    if not recent_a_ext: recent_a_ext = w_res.get("recentAwayAwayResults", [])

    h2h20 = comp.get("headtohead", []) if isinstance(comp.get("headtohead"), list) else []

    h_dom_w = w_avg.get("homeTeam", {}).get("home", {}) if isinstance(w_avg.get("homeTeam"), dict) else {}
    a_ext_w = w_avg.get("awayTeam", {}).get("away", {}) if isinstance(w_avg.get("awayTeam"), dict) else {}

    gf_a = h_dom_w.get("avgGoalsFor", 0.0)
    ga_a = h_dom_w.get("avgGoalsAg", 0.0)
    sot_a = h_dom_w.get("shotsOnTargetFor", 0.0)
    sota_a = h_dom_w.get("shotsOnTargetAg", 0.0)

    gf_b = a_ext_w.get("avgGoalsFor", 0.0)
    ga_b = a_ext_w.get("avgGoalsAg", 0.0)
    sot_b = a_ext_w.get("shotsOnTargetFor", 0.0)
    sota_b = a_ext_w.get("shotsOnTargetAg", 0.0)

    if gf_a == 0.0 and recent_h_dom:
        gf_a = sum(int(m.get("homeGoals", 0)) for m in recent_h_dom) / len(recent_h_dom)
        ga_a = sum(int(m.get("awayGoals", 0)) for m in recent_h_dom) / len(recent_h_dom)
        sot_a = (gf_a * 2.3) + 1.8
        sota_a = (ga_a * 2.1) + 1.5

    if gf_b == 0.0 and recent_a_ext:
        gf_b = sum(int(m.get("awayGoals", 0)) for m in recent_a_ext) / len(recent_a_ext)
        ga_b = sum(int(m.get("homeGoals", 0)) for m in recent_a_ext) / len(recent_a_ext)
        sot_b = (gf_b * 2.3) + 1.8
        sota_b = (ga_b * 2.1) + 1.5

    if gf_a == 0.0: gf_a = 1.4; ga_a = 1.2; sot_a = 4.5; sota_a = 3.2
    if gf_b == 0.0: gf_b = 1.2; ga_b = 1.4; sot_b = 4.1; sota_b = 4.0

    xg_a = (sot_a * 0.28) + (gf_a * 0.5)
    xga_a = (sota_a * 0.28) + (ga_a * 0.5)
    xg_b = (sot_b * 0.28) + (gf_b * 0.5)
    xga_b = (sota_b * 0.28) + (ga_b * 0.5)

    def count_o25(matches_list):
        cnt = 0
        if isinstance(matches_list, list):
            for m in matches_list:
                if isinstance(m, dict):
                    gh = m.get("homeGoals", m.get("homeGoalsFt", 0))
                    ga = m.get("awayGoals", m.get("awayGoalsFt", 0))
                    try:
                        if (int(gh) + int(ga)) >= 3: cnt += 1
                    except Exception: pass
        return cnt

    o25_h_cnt = count_o25(recent_h_all[:20])
    o25_a_cnt = count_o25(recent_a_all[:20])
    o25_avg_rate = (((o25_h_cnt / max(1, len(recent_h_all[:20]))) + (o25_a_cnt / max(1, len(recent_a_all[:20])))) / 2.0) * 100

    xg_total = xg_a + ga_b*0.5 + xg_b + ga_a*0.5
    sot_total = sot_a + sot_b

    ds_a = (sot_a >= 5.5 and sota_b >= 4.5) or (gf_a >= 1.7 and ga_b >= 1.4) or (xg_a >= 1.8 and ga_b >= 1.4)
    ds_b = (sot_b >= 5.0 and sota_a >= 4.5) or (gf_b >= 1.6 and ga_a >= 1.4) or (xg_b >= 1.6 and ga_a >= 1.4)

    convergences = []
    if gf_a >= 1.8 and ga_b >= 1.4: convergences.append("Attaque domicile forte × défense extérieure fragile")
    if gf_b >= 1.6 and ga_a >= 1.4: convergences.append("Attaque extérieure productive × défense domicile permissive")
    if xg_a >= 1.7 and xg_b >= 1.5: convergences.append("xG des deux équipes favorables à la création d'occasions")
    if sot_a >= 5.5 and sot_b >= 5.0: convergences.append("Volume de tirs cadrés élevé des deux côtés")
    if o25_avg_rate >= 60.0: convergences.append(f"Forte fréquence historique de matchs à 3+ buts sur 20 matchs ({o25_avg_rate:.0f}%)")
    h2h_o25 = count_o25(h2h20[:10])
    if h2h20 and (h2h_o25 / max(1, len(h2h20[:10]))) >= 0.70:
        convergences.append(f"Historique H2H à {int(h2h_o25/len(h2h20[:10])*100)}%+ d'Over 2.5")

    red_flags = []
    if gf_a < 1.0: red_flags.append(f"Attaque A faible ({gf_a:.1f} goal/m)")
    if gf_b < 1.0: red_flags.append(f"Attaque B faible ({gf_b:.1f} goal/m)")
    if sot_total < 6.5: red_flags.append(f"Tirs cadrés faibles ({sot_total:.1f}/m)")
    if sot_total >= 11.0 and xg_total < 2.5:
        red_flags.append(f"Contradiction : Beaucoup de tirs cadrés ({sot_total:.1f}/m) mais xG faibles ({xg_total:.2f})")

    pts_xg = 25 if xg_total >= 3.5 else 22 if xg_total >= 3.0 else 18 if xg_total >= 2.6 else 14 if xg_total >= 2.2 else 9
    pts_buts = 20 if (gf_a+ga_a+gf_b+ga_b) >= 5.5 else 17 if (gf_a+ga_a+gf_b+ga_b) >= 4.5 else 14 if (gf_a+ga_a+gf_b+ga_b) >= 3.8 else 10
    pts_o25 = 15 if o25_avg_rate >= 75 else 12 if o25_avg_rate >= 60 else 9 if o25_avg_rate >= 50 else 6
    pts_tirs = 15 if sot_total >= 11.5 else 12 if sot_total >= 9.5 else 9 if sot_total >= 7.5 else 5
    pts_dom_ext = min(10, int((o25_h_cnt + o25_a_cnt) * 0.4))
    pts_comp = 4

    raw_score = min(100, pts_xg + pts_buts + pts_o25 + pts_tirs + pts_dom_ext + pts_comp)
    total_score = max(0, min(100, raw_score - (len(red_flags) * 12)))
    calibrated_prob = int((o25_avg_rate * 0.60) + (min(90, int(xg_total * 18)) * 0.40))
    if red_flags: calibrated_prob = max(25, calibrated_prob - (len(red_flags) * 8))

    if total_score >= 85 and len(red_flags) == 0 and len(convergences) >= 3: confiance = "TRÈS ÉLEVÉE"
    elif total_score >= 72 and len(red_flags) <= 1: confiance = "ÉLEVÉE"
    elif total_score >= 55: confiance = "MOYENNE"
    else: confiance = "FAIBLE"

    if total_score >= 82 and len(red_flags) == 0 and ds_a and ds_b:
        verdict = "🔥 TRÈS FORT PROFIL STATISTIQUE POUR 3+ BUTS"
    elif total_score >= 68 and len(red_flags) <= 1:
        verdict = "🟢 BON PROFIL STATISTIQUE POUR 3+ BUTS"
    elif total_score >= 50:
        verdict = "🟠 PROFIL INCERTAIN"
    else:
        verdict = "❌ PROFIL STATISTIQUE INSUFFISANT"

    if is_batch:
        return {
            "team_a": team_a,
            "team_b": team_b,
            "league": league,
            "score": total_score,
            "prob": calibrated_prob,
            "xg_total": round(xg_total, 2),
            "sot_total": round(sot_total, 1),
            "verdict": verdict,
            "red_flags": red_flags
        }

    print(f"⚽ {team_a.upper()} — {team_b.upper()}")
    print(f"\n🔥 SCORE 3+ BUTS : {total_score}/100")
    print(f"📊 PROBABILITÉ STATISTIQUE : {calibrated_prob} %")
    print(f"🛡️ CONFIANCE : {confiance}\n")

    print(f"### POTENTIEL ÉQUIPE A ({team_a} à Domicile)")
    print(f"• Buts marqués domicile : {gf_a:.1f}/match")
    print(f"• xG domicile implicite : {xg_a:.2f}")
    print(f"• Tirs cadrés produits : {sot_a:.1f}/match")
    print(f"• Défense adverse / buts encaissés extérieur : {ga_b:.1f}/match")
    print(f"• Tirs cadrés concédés par l'adversaire : {sota_b:.1f}/match")

    print(f"\n### POTENTIEL ÉQUIPE B ({team_b} à l'Extérieur)")
    print(f"• Buts marqués extérieur : {gf_b:.1f}/match")
    print(f"• xG extérieur implicite : {xg_b:.2f}")
    print(f"• Tirs cadrés produits : {sot_b:.1f}/match")
    print(f"• Défense adverse / buts encaissés domicile : {ga_a:.1f}/match")
    print(f"• Tirs cadrés concédés par l'adversaire : {sota_a:.1f}/match")

    print("\n### CONVERGENCES")
    if convergences:
        for c in convergences: print(f"✅ {c}")
    else: print("ℹ️ Aucune convergence multi-signaux majeure identifiée.")

    print("\n### DOUBLE SIGNAUX")
    if ds_a: print(f"✅ DOUBLE SIGNAL ÉQUIPE A ({team_a}) : Attaque domicile forte + Défense adverse fragile")
    else: print(f"❌ Pas de Double Signal complet pour l'Équipe A ({team_a})")

    if ds_b: print(f"✅ DOUBLE SIGNAL ÉQUIPE B ({team_b}) : Attaque extérieure productive + Défense adverse permissive")
    else: print(f"❌ Pas de Double Signal complet pour l'Équipe B ({team_b})")

    print("\n### RED FLAGS")
    if red_flags:
        for rf in red_flags: print(f"⚠️ RED FLAG : {rf}")
    else: print("✅ Aucun Red Flag majeur détecté.")

    print("\n### 📜 10 DERNIERS SCORES À DOMICILE — " + team_a.upper())
    for m in recent_h_dom[:10]:
        dt = m.get("date", "N/A")
        opp = m.get("vs", m.get("awayTeam", "Adversaire"))
        hg = m.get("homeGoals", m.get("homeGoalsFt", 0))
        ag = m.get("awayGoals", m.get("awayGoalsFt", 0))
        tot = int(hg) + int(ag)
        icon = "🔥 3+ buts" if tot >= 3 else "⚪ < 3 buts"
        print(f"  • {dt} vs {opp:<20} | Score : {hg}-{ag} ({tot} buts) [{icon}]")

    print("\n### 📜 10 DERNIERS SCORES À L'EXTÉRIEUR — " + team_b.upper())
    for m in recent_a_ext[:10]:
        dt = m.get("date", "N/A")
        opp = m.get("vs", m.get("homeTeam", "Adversaire"))
        hg = m.get("homeGoals", m.get("homeGoalsFt", 0))
        ag = m.get("awayGoals", m.get("awayGoalsFt", 0))
        tot = int(hg) + int(ag)
        icon = "🔥 3+ buts" if tot >= 3 else "⚪ < 3 buts"
        print(f"  • {dt} vs {opp:<20} | Score : {hg}-{ag} ({tot} buts) [{icon}]")

    print("\n### VERDICT FINAL")
    print(f"{verdict}\n")

def parse_line(line):
    line = re.sub(r'^\d{1,2}:\d{2}\s*', '', line.strip())
    for sep in [" vs ", " v ", " contre ", " - ", " / ", " – ", " — "]:
        if sep in line.lower():
            parts = line.lower().split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    words = line.strip().split()
    if len(words) == 2:
        return words[0], words[1]
    if len(words) == 4:
        return f"{words[0]} {words[1]}", f"{words[2]} {words[3]}"
    if len(words) == 3:
        return f"{words[0]} {words[1]}", words[2]
    return None, None

def process_batch_lines(lines):
    matches_list = []
    for line in lines:
        if not line.strip(): continue
        h, a = parse_line(line)
        if h and a:
            matches_list.append((h, a))

    if not matches_list:
        print("⚠️ Aucun match valide détecté dans votre copier-coller.")
        return

    print(f"\n================================================================================")
    print(f"📊 CLASSEMENT BATCH ({len(matches_list)} MATCHS ANALYSÉS EN PARALLÈLE)")
    print(f"================================================================================")
    fx_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(analyze_pure_stats_20, h, a, fx_data, True) for h, a in matches_list]
        for f in futs:
            try:
                res = f.result()
                if res: results.append(res)
            except Exception: pass

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, res in enumerate(results, 1):
        rf_str = f" | ⚠️ {', '.join(res['red_flags'])}" if res['red_flags'] else ""
        print(f"#{i:02d} {res['team_a'].upper()} vs {res['team_b'].upper()} ({res['league']}) — SCORE: {res['score']}/100 | Prob: {res['prob']}%")
        print(f"     VERDICT: {res['verdict']}{rf_str}")
    print("================================================================================\n")

def interactive_paste_mode():
    print("📋 MODE COPIER-COLLER INTERACTIF POWERSHELL")
    print("Collez votre liste de matchs ci-dessous (un match par ligne).")
    print("👉 Appuyez sur ENTRÉE DEUX FOIS lorsque vous avez fini de coller :\n")
    
    lines = []
    while True:
        try:
            line = input()
            if not line.strip():
                break
            lines.append(line.strip())
        except EOFError:
            break
            
    if lines:
        process_batch_lines(lines)

def parse_cli_args():
    if len(sys.argv) <= 1:
        return None, None
    args = sys.argv[1:]
    if len(args) == 2:
        return args[0], args[1]
    full_str = " ".join(args)
    for sep in [" vs ", " v ", " contre ", " - ", " / ", " – ", " — "]:
        if sep in full_str.lower():
            parts = full_str.lower().split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    if len(args) == 4:
        return f"{args[0]} {args[1]}", f"{args[2]} {args[3]}"
    if len(args) == 3:
        return f"{args[0]} {args[1]}", args[2]
    return args[0], " ".join(args[1:])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        filepath = sys.argv[2] if len(sys.argv) > 2 else "matches.txt"
        if not os.path.exists(filepath):
            print(f"❌ Fichier '{filepath}' introuvable.")
            sys.exit(0)
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        process_batch_lines(lines)

    elif len(sys.argv) > 1 and sys.argv[1] == "--today":
        print("\n================================================================================")
        print("📊 CLASSEMENT AUTOMATIQUE DE TOUS LES MATCHS DU JOUR (PARALLÈLE)")
        print("================================================================================")
        fx_data = fetch(f"{BASE}/scripts/data/json/scripts/getFixturesJsonForSearch.php?clflc=abc&timezoneOffset=0")
        matches_list = []
        for d in fx_data.get("dates", [])[:1]:
            for lg in d.get("leagues", []):
                for fx in lg.get("fixtures", []):
                    matches_list.append((fx["hometeam"], fx["awayteam"]))
        results = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(analyze_pure_stats_20, h, a, fx_data, True) for h, a in matches_list]
            for f in futs:
                try:
                    res = f.result()
                    if res and res["score"] >= 50: results.append(res)
                except Exception: pass
        results.sort(key=lambda x: x["score"], reverse=True)
        for i, res in enumerate(results, 1):
            rf_str = f" | ⚠️ {', '.join(res['red_flags'])}" if res['red_flags'] else ""
            print(f"#{i:02d} {res['team_a'].upper()} vs {res['team_b'].upper()} ({res['league']}) — SCORE: {res['score']}/100 | Prob: {res['prob']}%")
            print(f"     VERDICT: {res['verdict']}{rf_str}")
        print("================================================================================\n")

    elif len(sys.argv) > 1 and sys.argv[1] == "--paste":
        interactive_paste_mode()

    elif len(sys.argv) == 1:
        interactive_paste_mode()

    else:
        home, away = parse_cli_args()
        if home and away:
            analyze_pure_stats_20(home, away)
        else:
            interactive_paste_mode()
