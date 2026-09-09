import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) >= 20, f"Expected at least 20 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") + summary.get("lost") == summary.get("decided_combos"), "Won + lost mismatch"
assert summary.get("decided_combos") + summary.get("live") + summary.get("upcoming") == len(combos), "Status count mismatch"

# Verify Ticket #6: Sarpsborg 08 + Molde (@2.24) WON
t6 = combos[5]
assert "Sarpsborg" in t6["m1"]["home"]
assert "Molde" in t6["m2"]["home"]
assert t6["ticket_status"] == "WON"

# Verify Ticket #13: Palestino + Corinthians (@2.35) -> LOST
t13 = combos[12]
assert "Palestino" in t13["m1"]["home"]
assert "Corinthians" in t13["m2"]["home"]
assert t13["ticket_status"] == "LOST"

# Verify Ticket #23: Al Ittihad + Southampton (@2.41) -> WON
t23 = combos[22]
assert "Ittihad" in t23["m1"]["home"]
assert "Southampton" in t23["m2"]["home"]
assert t23["ticket_status"] == "WON"

# Verify Ticket #24: Dortmund + Real Madrid (@2.67) -> WON
t24 = combos[23]
assert "Dortmund" in t24["m1"]["home"]
assert "Real Madrid" in t24["m2"]["home"]
assert t24["ticket_status"] == "WON"

# Verify multi-market card rendering and proof guards
import sys
sys.path.insert(0, ".")
import scripts.auto_premium_unibet as apu
m_o15 = {'fav_info': {'market': 'OVER_15', 'fav_team': 'Over 1.5 Buts', 'fav_score': 80, 'fav_odds': 1.30, 'fav_badge': '⚽ OVER 1.5', 'pct_fav_success': 85}}
m_btts = {'fav_info': {'market': 'BTTS', 'fav_team': 'Les 2 Marquent', 'fav_score': 75, 'fav_odds': 1.80, 'fav_badge': '🤝 BTTS', 'pct_fav_success': 70}}
m_fav = {'fav_info': {'market': 'FAV_1N2', 'fav_team': 'Arsenal', 'dog_team': 'Chelsea', 'fav_side': 'dom', 'fav_score': 80, 'fav_odds': 1.60, 'fav_badge': '🥇 OR', 'pct_fav_success': 80, 'pct_fav_win': 70, 'pct_fav_lead2': 50, 'pct_fav_cs': 40, 'avg_fav_gf': 2.0, 'pct_dog_loss': 60, 'pct_dog_trailed2': 40, 'pct_dog_no_goal': 30, 'avg_dog_ga': 1.5}}

assert apu.render_fav_proof_html(m_o15) == ""
assert apu.render_fav_proof_html(m_btts) == ""

print("✅ TOUS LES TESTS ASSERTIONS PASSENT AVEC SUCCÈS (100% Validé) !")

