from datetime import datetime, timezone

def test_combos_2matches_logic():
    MIN_O25_ODDS = 1.55
    MIN_COMB_ODDS = 2.20

    # 4 matchs avec cotes over25 et under25
    # m1: Over favori (1.65 < 2.10)
    # m2: Over favori (1.70 < 2.05)
    # m3: Under favori (1.80 > 1.70) -> Doit etre exclu car Over non favori !
    # m4: Over favori (1.75 < 1.95)
    raw_matches = [
        {"id": "m1", "dom": "Arsenal", "ext": "Chelsea", "over25": 1.65, "under25": 2.10, "ac_score": 85, "dt": datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)},
        {"id": "m2", "dom": "Liverpool", "ext": "Everton", "over25": 1.70, "under25": 2.05, "ac_score": 88, "dt": datetime(2026, 9, 5, 18, 30, tzinfo=timezone.utc)},
        {"id": "m3", "dom": "PSG", "ext": "Marseille", "over25": 1.80, "under25": 1.70, "ac_score": 82, "dt": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc)},
        {"id": "m4", "dom": "Monaco", "ext": "Nice", "over25": 1.75, "under25": 1.95, "ac_score": 84, "dt": datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc)},
    ]

    # Filtrage s3_matches
    s3_matches = []
    rejected = []
    for r in raw_matches:
        ac_score = r.get("ac_score", 0)
        o25 = r.get("over25")
        u25 = r.get("under25")
        is_o25_fav = (o25 is not None and u25 is not None and o25 < u25)

        if ac_score >= 80 and o25 is not None and o25 >= MIN_O25_ODDS and is_o25_fav:
            s3_matches.append(r)
        else:
            rejected.append(r)

    # Verifier que m3 a bien ete rejete car Under favori
    assert len(s3_matches) == 3, f"Attendu 3 retenus, obtenu {len(s3_matches)}"
    assert "m3" not in [m["id"] for m in s3_matches]
    assert "m3" in [m["id"] for m in rejected]
    assert all(m["over25"] < m["under25"] for m in s3_matches)

    # Formation des combines de 2 matchs
    def get_match_teams(m_dict):
        d = (m_dict.get("dom") or "").strip().lower()
        e = (m_dict.get("ext") or "").strip().lower()
        return {x for x in [d, e] if x}

    block_items = sorted(
        [{"m": m, "id": m["id"], "odds": m["over25"], "score": m["ac_score"], "dt": m["dt"]} for m in s3_matches],
        key=lambda x: (x["score"], x["odds"]),
        reverse=True
    )

    used_match_ids = set()
    used_teams = set()
    combos_mixed = []
    TARGET_COMB = 2.20

    for i, s1 in enumerate(block_items):
        if s1["id"] in used_match_ids:
            continue
        t1 = get_match_teams(s1["m"])
        if t1 & used_teams:
            continue

        best_partner = None
        best_diff = 999.0
        best_t2 = None

        for s2 in block_items[i+1:]:
            if s2["id"] in used_match_ids or s2["id"] == s1["id"]:
                continue
            t2 = get_match_teams(s2["m"])
            if (t2 & used_teams) or (t1 & t2):
                continue

            comb = round(s1["odds"] * s2["odds"], 2)
            if comb < MIN_COMB_ODDS:
                continue
            diff = abs(comb - TARGET_COMB)
            if diff < best_diff:
                best_diff = diff
                best_partner = s2
                best_t2 = t2

        if best_partner and best_t2:
            used_match_ids.add(s1["id"])
            used_match_ids.add(best_partner["id"])
            used_teams.update(t1 | best_t2)

            comb_odds = round(s1["odds"] * best_partner["odds"], 2)
            items = sorted([s1, best_partner], key=lambda x: x["dt"])
            stake = 4.00
            gain = round(stake * comb_odds, 2)
            profit = round(gain - stake, 2)

            combos_mixed.append({
                "type": "Doublé Over 2.5",
                "items": items,
                "comb_odds": comb_odds,
                "stake": stake,
                "gain": gain,
                "profit": profit,
            })

    assert len(combos_mixed) == 1
    cb = combos_mixed[0]
    assert len(cb["items"]) == 2
    assert cb["comb_odds"] >= MIN_COMB_ODDS
    assert cb["comb_odds"] == round(block_items[0]["odds"] * block_items[1]["odds"], 2)
    assert cb["stake"] == 4.00
    assert cb["gain"] == round(4.00 * cb["comb_odds"], 2)
    assert all(it["m"]["over25"] < it["m"]["under25"] for it in cb["items"])

    print("PASS: test_combos_2matches_logic passed successfully!")

if __name__ == "__main__":
    test_combos_2matches_logic()
