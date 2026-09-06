import json

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

combos = d.get("combos_today", [])
summary = d.get("combos_summary", {})

assert len(combos) == 20, f"Expected 20 combos, got {len(combos)}"
assert summary.get("default_stake") == 3.0, f"Expected stake 3.0, got {summary.get('default_stake')}"
assert summary.get("won") == 6, f"Expected 6 won, got {summary.get('won')}"
assert summary.get("lost") == 4, f"Expected 4 lost, got {summary.get('lost')}"
assert summary.get("upcoming") == 8, f"Expected 8 upcoming, got {summary.get('upcoming')}"

# Verify Ticket #6: Sarpsborg 08 + Molde (@2.24) WON
t6 = combos[5]
assert "Sarpsborg" in t6["m1"]["home"]
assert "Molde" in t6["m2"]["home"]
assert t6["ticket_status"] == "WON"
assert t6["odds"] == 2.24
assert t6["gain_eur"] == 6.70

# Verify Ticket #13 (Email #1): Palestino + Corinthians (@2.35)
t13 = combos[12]
assert t13["email_ticket_num"] == 1
assert "Palestino" in t13["m1"]["home"]
assert "Corinthians" in t13["m2"]["home"]
assert t13["ticket_status"] == "PENDING"
assert t13["odds"] == 2.35

# Verify Ticket #14 (Email #2): Cruz Azul + SD Aucas (@2.10)
t14 = combos[13]
assert t14["email_ticket_num"] == 2
assert "Cruz Azul" in t14["m1"]["home"]
assert "Aucas" in t14["m2"]["home"]
assert t14["odds"] == 2.10

# Verify Ticket #20 (Email #8): Vitoria BA + Emelec (@2.84)
t20 = combos[19]
assert t20["email_ticket_num"] == 8
assert "Vitoria" in t20["m1"]["home"]
assert "Emelec" in t20["m2"]["home"]
assert t20["odds"] == 2.84

print("✅ TOUS LES TESTS ASSERTIONS (20 COMBINÉS DONT 6 GAGNÉS ET 8 DU MAIL) PASSENT AVEC SUCCÈS (100% Validé) !")
