"""
refresh_live.py — Met à jour uniquement les scores en direct dans matches.json
Sans re-scraper Unibet (rapide: ~3 secondes)
Lancer en boucle : python refresh_live.py
"""
import json, re, time, requests
from datetime import datetime, timezone
from difflib import SequenceMatcher

MATCHES_JSON = r"C:\Users\grego\Documents\DEV_DIVERS\penalty\dashboard\public\data\matches.json"

def sim(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def normalize(name):
    return re.sub(r'\s+(FC|SC|CF|AS|AC|1\.|FK|BK|SK|IF|IK|GF|FF|VPS|Utd|United|City|Town|Club|Sporting|Real)\b',
                  '', name or '', flags=re.IGNORECASE).strip().lower()

def fetch_live():
    today = datetime.now().strftime("%Y%m%d")
    r = requests.get(f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{today}/0",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    events = []
    for st in r.json().get("Stages", []):
        stage = (st.get("Cnm", "") + " • " + st.get("Snm", "")).strip()
        for ev in st.get("Events", []):
            eps = str(ev.get("Eps", ""))
            if eps not in ["NS", "FT", "AP", "AET", "CANC", "POST", "DEFD"]:
                h = ev.get("T1", [{}])[0].get("Nm", "")
                a = ev.get("T2", [{}])[0].get("Nm", "")
                events.append({
                    "id": str(ev.get("Eid", "")),
                    "home": h, "away": a,
                    "score_dom": int(ev.get("Tr1", 0) or 0),
                    "score_ext": int(ev.get("Tr2", 0) or 0),
                    "minute": eps + ("'" if eps.isdigit() else ""),
                    "period_label": "En cours" if eps.isdigit() else eps,
                    "league": stage
                })
    return events

def main():
    print("=== REFRESH LIVE (LiveScore) — mise à jour toutes les 2 min ===")
    while True:
        try:
            with open(MATCHES_JSON, encoding="utf-8") as f:
                data = json.load(f)

            live_events = fetch_live()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] LiveScore: {len(live_events)} matchs en cours")

            new_matches = []
            live_count = 0
            for m in data["matches"]:
                if m["status"] in ("FINISHED",):
                    new_matches.append(m)
                    continue

                # Chercher correspondance dans le live
                dom, ext = m.get("dom", ""), m.get("ext", "")
                best_sim, best_ev = 0.0, None
                for ev in live_events:
                    s = (sim(normalize(dom), normalize(ev["home"])) +
                         sim(normalize(ext), normalize(ev["away"]))) / 2.0
                    if s > best_sim:
                        best_sim, best_ev = s, ev

                if best_ev and best_sim >= 0.60:
                    buts = best_ev["score_dom"] + best_ev["score_ext"]
                    is_won = buts >= 3
                    live_count += 1
                    m = {**m,
                         "status": "LIVE",
                         "date_str": "En Direct",
                         "score_dom": best_ev["score_dom"],
                         "score_ext": best_ev["score_ext"],
                         "minute": best_ev["minute"],
                         "period_label": best_ev["period_label"],
                         "selection_status": "WON" if is_won and m.get("is_selected") else ("LOST" if m["status"] == "LIVE" and not is_won else "PENDING"),
                    }
                    if m.get("is_selected"):
                        print(f"  🔴 LIVE: {dom} vs {ext} => {best_ev['home']} {best_ev['score_dom']}-{best_ev['score_ext']} {best_ev['away']} [{best_ev['minute']}]")
                elif m["status"] == "LIVE":
                    # Match qui était live mais n'est plus dans le feed = terminé
                    m = {**m, "status": "FINISHED"}

                new_matches.append(m)

            data["matches"] = new_matches
            data["summary"]["total_live"] = live_count
            data["summary"]["last_update"] = datetime.now(timezone.utc).isoformat()

            with open(MATCHES_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"  ✅ JSON mis à jour — {live_count} matchs sélectionnés EN DIRECT")

        except Exception as e:
            print(f"  ⚠️ Erreur: {e}")

        time.sleep(120)  # toutes les 2 minutes

if __name__ == "__main__":
    main()
