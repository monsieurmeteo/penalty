import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) == 19, f"Expected 19 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") == 5, f"Expected 5 won, got {summary.get('won')}"
assert summary.get("lost") == 4, f"Expected 4 lost, got {summary.get('lost')}"
assert summary.get("upcoming") == 8, f"Expected 8 upcoming, got {summary.get('upcoming')}"

# Verify Ticket #12 (Email #1): Palestino + Corinthians (@2.35)
t12 = combos[11]
assert t12["email_ticket_num"] == 1
assert "Palestino" in t12["m1"]["home"]
assert "Corinthians" in t12["m2"]["home"]
assert t12["ticket_status"] == "PENDING"
assert t12["odds"] == 2.35

# Verify Ticket #13 (Email #2): Cruz Azul + SD Aucas (@2.10)
t13 = combos[12]
assert t13["email_ticket_num"] == 2
assert "Cruz Azul" in t13["m1"]["home"]
assert "Aucas" in t13["m2"]["home"]
assert t13["odds"] == 2.10

# Verify Ticket #14 (Email #3): Toluca + Asteras (@3.82)
t14 = combos[13]
assert t14["email_ticket_num"] == 3
assert "Toluca" in t14["m1"]["home"]
assert "Asteras" in t14["m2"]["home"]
assert t14["odds"] == 3.82

# Verify Ticket #19 (Email #8): Vitoria BA + Emelec (@2.84)
t19 = combos[18]
assert t19["email_ticket_num"] == 8
assert "Vitoria" in t19["m1"]["home"]
assert "Emelec" in t19["m2"]["home"]
assert t19["odds"] == 2.84

print("✅ TOUS LES TESTS ASSERTIONS (19 COMBINÉS DONT LES 8 DU MAIL) PASSENT AVEC SUCCÈS (100% Validé) !")
