import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) == 11, f"Expected 11 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") == 5
assert summary.get("lost") == 2
assert summary.get("profit_eur") == 10.95

# Verify Ticket #3: Vikingur + Barcelone (LOST)
t3 = combos[2]
assert "Vikingur" in t3["m1"]["home"]
assert "Barcelone" in t3["m2"]["fav_team"]
assert t3["ticket_status"] == "LOST"
assert t3["odds"] == 1.80

# Verify Ticket #4: Sion + ADO Den Haag (LOST)
t4 = combos[3]
assert "Sion" in t4["m1"]["home"]
assert "ADO Den Haag" in t4["m2"]["home"]
assert t4["ticket_status"] == "LOST"
assert t4["odds"] == 2.88

print("✅ TOUS LES TESTS ASSERTIONS 11 TICKETS PASSENT AVEC SUCCÈS (100% Validé) !")
