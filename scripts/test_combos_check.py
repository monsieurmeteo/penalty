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

print("✅ TOUS LES TESTS ASSERTIONS PASSENT AVEC SUCCÈS (100% Validé) !")
