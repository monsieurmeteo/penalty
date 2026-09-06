import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) == 16, f"Expected 16 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") == 5
assert summary.get("upcoming") == 5

# Verify Ticket #12: River Plate + Palestino (Option A from email)
t12 = combos[11]
assert "River Plate" in t12["m1"]["home"]
assert "Palestino" in t12["m2"]["home"]
assert t12["ticket_status"] == "PENDING"
assert t12["odds"] == 2.74

# Verify Ticket #13: Dep. Cuenca + Toluca (Option A from email)
t13 = combos[12]
assert "Dep.Cuenca" in t13["m1"]["home"]
assert "Toluca" in t13["m2"]["home"]
assert t13["ticket_status"] == "PENDING"
assert t13["odds"] == 3.47

print("✅ TOUS LES TESTS ASSERTIONS OPTION A PASSENT AVEC SUCCÈS (100% Validé) !")
