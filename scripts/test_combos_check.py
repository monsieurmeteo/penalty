import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) == 18, f"Expected 18 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"

# Verify Ticket #5: FC Tokyo + Paide
t5 = combos[4]
assert "FC Tokyo" in t5["m1"]["home"]
assert "Paide" in t5["m2"]["home"]
assert t5["ticket_status"] == "WON"
assert t5["odds"] == 2.35

# Verify Ticket #11: Kaizer Chiefs + Lech Poznan
t11 = combos[10]
assert "Kaizer" in t11["m1"]["home"]
assert "Lech" in t11["m2"]["home"]
assert t11["ticket_status"] == "WON"
assert t11["odds"] == 2.40

# Verify Ticket #13: OFI Crete + Guimaraes
t13 = combos[12]
assert "OFI" in t13["m1"]["home"]
assert "Guimaraes" in t13["m2"]["home"]

# Verify Ticket #14: Rosario + Gyor
t14 = combos[13]
assert "Rosario" in t14["m1"]["home"]
assert "Györ" in t14["m2"]["home"] or "Gyor" in t14["m2"]["home"]

# Verify Ticket #15: Vojvodina + Libertad
t15 = combos[14]
assert "Vojvodina" in t15["m1"]["home"]
assert "Libertad" in t15["m2"]["home"]

# Verify Ticket #16: Almeria + Huachipato
t16 = combos[15]
assert "Almeria" in t16["m1"]["home"]
assert "Huachipato" in t16["m2"]["home"]

print("✅ TOUS LES TESTS ASSERTIONS COMBINÉS PASSENT AVEC SUCCÈS (100% Validé) !")
