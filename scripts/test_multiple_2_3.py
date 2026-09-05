from datetime import datetime, timezone

def test_multiple_2_3_logic():
    MIN_O25_ODDS = 1.55
    MIN_COMB_ODDS = 2.20

    items = [
        {"id": "m1", "dom": "Arsenal", "ext": "Chelsea", "odds": 1.65, "score": 85, "dt": datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc), "m": {"dom": "Arsenal", "ext": "Chelsea"}},
        {"id": "m2", "dom": "Liverpool", "ext": "Everton", "odds": 1.70, "score": 88, "dt": datetime(2026, 9, 5, 18, 30, tzinfo=timezone.utc), "m": {"dom": "Liverpool", "ext": "Everton"}},
        {"id": "m3", "dom": "PSG", "ext": "Marseille", "odds": 1.60, "score": 82, "dt": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc), "m": {"dom": "PSG", "ext": "Marseille"}},
        {"id": "m4", "dom": "Monaco", "ext": "Nice", "odds": 1.75, "score": 84, "dt": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc), "m": {"dom": "Monaco", "ext": "Nice"}},
    ]

    def get_match_teams(m_dict):
        d = (m_dict.get("dom") or "").strip().lower()
        e = (m_dict.get("ext") or "").strip().lower()
        return {x for x in [d, e] if x}

    used_match_ids = set()
    used_teams = set()
    combos_mixed = []

    for i in range(len(items)):
        s1 = items[i]
        if s1["id"] in used_match_ids:
            continue
        t1 = get_match_teams(s1["m"])
        if t1 & used_teams:
            continue

        found_triplet = None
        for j in range(i + 1, len(items)):
            s2 = items[j]
            if s2["id"] in used_match_ids:
                continue
            t2 = get_match_teams(s2["m"])
            if (t2 & used_teams) or (t1 & t2):
                continue

            for k in range(j + 1, len(items)):
                s3 = items[k]
                if s3["id"] in used_match_ids:
                    continue
                t3 = get_match_teams(s3["m"])
                if (t3 & used_teams) or (t1 & t3) or (t2 & t3):
                    continue

                found_triplet = (s1, s2, s3, t1, t2, t3)
                break
            if found_triplet:
                break

        if found_triplet:
            s1, s2, s3, t1, t2, t3 = found_triplet
            used_match_ids.update([s1["id"], s2["id"], s3["id"]])
            used_teams.update(t1 | t2 | t3)

            triplet = sorted([s1, s2, s3], key=lambda x: x["dt"])
            c12 = round(triplet[0]["odds"] * triplet[1]["odds"], 2)
            c13 = round(triplet[0]["odds"] * triplet[2]["odds"], 2)
            c23 = round(triplet[1]["odds"] * triplet[2]["odds"], 2)
            pair_odds = [c12, c13, c23]

            stake_per_comb = 1.50
            total_stake = 4.50
            min_win_odds = min(pair_odds)
            max_win_odds = sum(pair_odds)
            min_gain = round(stake_per_comb * min_win_odds, 2)
            max_gain = round(stake_per_comb * max_win_odds, 2)
            max_profit = round(max_gain - total_stake, 2)

            combos_mixed.append({
                "type": "Multiple 2/3",
                "items": triplet,
                "pair_odds": pair_odds,
                "comb_odds": round(c12 * triplet[2]["odds"], 2),
                "stake_per_comb": stake_per_comb,
                "total_stake": total_stake,
                "min_gain": min_gain,
                "max_gain": max_gain,
                "profit": max_profit,
            })

    assert len(combos_mixed) == 1
    cb = combos_mixed[0]
    assert len(cb["items"]) == 3
    assert cb["total_stake"] == 4.50
    assert cb["stake_per_comb"] == 1.50
    assert all(it["score"] >= 80 for it in cb["items"])
    assert all(it["odds"] >= MIN_O25_ODDS for it in cb["items"])
    assert all(p >= MIN_COMB_ODDS for p in cb["pair_odds"])
    assert cb["min_gain"] == round(1.50 * min(cb["pair_odds"]), 2)
    # Test formatage chaîne HTML et report
    p12, p13, p23 = cb['pair_odds']
    header_html = f"TICKET MULTIPLE 2/3 #1 — Mise : {cb['total_stake']:.2f} € (3 × {cb['stake_per_comb']:.2f} €)"
    footer_html = f"Double 1-2 : @{p12:.2f} | Min. {cb['min_gain']:.2f} € | Gain Max {cb['max_gain']:.2f} € (+{cb['profit']:.2f} € net)"
    assert "4.50 €" in header_html
    assert "1.50 €" in header_html
    assert f"@{p12:.2f}" in footer_html
    assert f"{cb['min_gain']:.2f} €" in footer_html
    assert f"{cb['max_gain']:.2f} €" in footer_html

    print("PASS: test_multiple_2_3_logic passed successfully!")

if __name__ == "__main__":
    test_multiple_2_3_logic()

