import json, os, sys
from datetime import datetime, timezone, timedelta

sys.path.append(r"C:\Users\grego\Documents\DEV_DIVERS\penalty")
from scripts.auto_premium_unibet import get_unibet_active_games, scan_unibet_match_details
from concurrent.futures import ThreadPoolExecutor, as_completed

def main():
    print("Scraping Unibet France en direct pour le rapport chat...")
    games = get_unibet_active_games()

    scanned = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(scan_unibet_match_details, g) for g in games]
        for f in as_completed(futs):
            res = f.result()
            if res:
                scanned.append(res)

    now_utc = datetime.now(timezone.utc)
    limit_48h = now_utc + timedelta(hours=48)
    window_matches = []
    for m in scanned:
        iso = m.get('start_iso')
        if iso:
            try:
                dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
                if now_utc <= dt <= limit_48h:
                    m['dt_obj'] = dt
                    window_matches.append(m)
            except Exception:
                window_matches.append(m)
        else:
            window_matches.append(m)

    all_o25 = [m['over25'] for m in window_matches if m.get('over25') is not None]
    all_s22 = [m['s22'] for m in window_matches if m.get('s22') is not None]

    SEUIL_S3 = 12.00
    MIN_O25 = 1.55
    MAX_O25 = 1.70

    selected = []
    rejected = []
    for m in window_matches:
        s22 = m.get('s22')
        o25 = m.get('over25')
        if s22 and s22 <= SEUIL_S3 and o25 and MIN_O25 <= o25 <= MAX_O25:
            selected.append(m)
        else:
            reasons = []
            if s22 is None: reasons.append("Score 2-2 N/A")
            elif s22 > SEUIL_S3: reasons.append(f"Score 2-2={s22:.2f} (>12.00)")

            if o25 is None: reasons.append("Over 2.5 N/A")
            elif o25 < MIN_O25: reasons.append(f"Over 2.5={o25:.2f} (<1.55)")
            elif o25 > MAX_O25: reasons.append(f"Over 2.5={o25:.2f} (>1.70)")

            m['reasons'] = " • ".join(reasons)
            rejected.append(m)

    selected.sort(key=lambda x: x.get('dt_obj', now_utc))
    rejected.sort(key=lambda x: x.get('dt_obj', now_utc))

    sel_o25 = [m['over25'] for m in selected if m.get('over25') is not None]
    sel_s22 = [m['s22'] for m in selected if m.get('s22') is not None]

    avg_all_o25 = sum(all_o25) / len(all_o25) if all_o25 else 0
    avg_all_s22 = sum(all_s22) / len(all_s22) if all_s22 else 0
    avg_sel_o25 = sum(sel_o25) / len(sel_o25) if sel_o25 else 0
    avg_sel_s22 = sum(sel_s22) / len(sel_s22) if sel_s22 else 0

    print("\n--- STATS GLOBALES MARCHÉ UNIBET 48H ---")
    print(f"Total matchs scannés 48h : {len(window_matches)}")
    print(f"Moyenne Cote Over 2.5 (Tous les {len(all_o25)} matchs) : {avg_all_o25:.2f}")
    print(f"Moyenne Cote Score 2-2 (Tous les {len(all_s22)} matchs) : {avg_all_s22:.2f}")
    print(f"\n--- MATCHS SELECTIONNES ({len(selected)}) ---")
    print(f"Moyenne Over 2.5 (Retenus) : {avg_sel_o25:.2f}")
    print(f"Moyenne Score 2-2 (Retenus) : {avg_sel_s22:.2f}\n")

    res = {
        "total_scanned": len(window_matches),
        "count_o25": len(all_o25),
        "avg_all_o25": round(avg_all_o25, 2),
        "count_s22": len(all_s22),
        "avg_all_s22": round(avg_all_s22, 2),
        "total_selected": len(selected),
        "avg_sel_o25": round(avg_sel_o25, 2),
        "avg_sel_s22": round(avg_sel_s22, 2),
        "selected": selected,
        "rejected": rejected
    }

    with open(r"C:\Users\grego\Documents\DEV_DIVERS\penalty\scratch_chat_res.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2, default=str)

if __name__ == "__main__":
    main()
