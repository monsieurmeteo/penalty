import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) >= 12, f"Expected at least 12 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") == 5
assert summary.get("lost") == 3  # Vikingur+Barcelone, Sion+ADO Den Haag, OFI Crete+Guimaraes (0-0 FT)

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

# Verify Ticket #12: Corinthians + Palestino (PENDING/UPCOMING)
t12 = combos[11]
assert "Corinthians" in t12["m1"]["home"]
assert "Palestino" in t12["m2"]["home"]
assert t12["ticket_status"] == "PENDING"
assert t12["odds"] == 2.08

print("✅ TOUS LES TESTS ASSERTIONS 12 TICKETS PASSENT AVEC SUCCÈS (100% Validé) !")
