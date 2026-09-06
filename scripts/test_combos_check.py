import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) >= 9, f"Expected at least 9 user combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"

# Verify Ticket #1: FC Tokyo + Paide
t1 = combos[0]
assert "FC Tokyo" in t1["m1"]["home"]
assert "Paide" in t1["m2"]["home"]
assert t1["ticket_status"] == "WON"
assert t1["odds"] == 1.90

# Verify Ticket #2: Eibar + Hearts
t2 = combos[1]
assert "Eibar" in t2["m1"]["home"]
assert "Hearts" in t2["m2"]["home"]
assert t2["ticket_status"] == "WON"
assert t2["odds"] == 2.55

# Verify Ticket #3: FK Auda + FK Kosice
t3 = combos[2]
assert "Auda" in t3["m1"]["home"]
assert "Kosice" in t3["m2"]["home"]
assert t3["ticket_status"] == "WON"
assert t3["odds"] == 1.87

# Verify Ticket #4: Lech Poznan + Kaizer Chiefs
t4 = combos[3]
assert "Lech" in t4["m1"]["home"]
assert "Kaizer" in t4["m2"]["home"]
assert t4["ticket_status"] == "WON"
assert t4["odds"] == 2.22

# Verify Ticket #5: Ferencvaros + Arsenal
t5 = combos[4]
assert "Ferencvaros" in t5["m1"]["home"]
assert "Arsenal" in t5["m2"]["home"]
assert t5["ticket_status"] == "WON"
assert t5["odds"] == 2.11

# Verify Ticket #6: OFI Crete + Guimaraes
t6 = combos[5]
assert "OFI" in t6["m1"]["home"]
assert "Guimaraes" in t6["m2"]["home"]

# Verify Ticket #7: Rosario + Gyor
t7 = combos[6]
assert "Rosario" in t7["m1"]["home"]
assert "Györ" in t7["m2"]["home"]

# Verify Ticket #8: Vojvodina + Libertad
t8 = combos[7]
assert "Vojvodina" in t8["m1"]["home"]
assert "Libertad" in t8["m2"]["home"]

# Verify Ticket #9: Almeria + Huachipato
t9 = combos[8]
assert "Almeria" in t9["m1"]["home"]
assert "Huachipato" in t9["m2"]["home"]

print("✅ TOUS LES TESTS ASSERTIONS COMBINÉS PASSENT AVEC SUCCÈS (100% Validé) !")
