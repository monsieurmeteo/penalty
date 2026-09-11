import json
import sys

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

# 1. Vérification Méthode 2
m2_combos = d.get("methode2_combos", [])
m2_summary = d.get("methode2_summary", {})

assert len(m2_combos) >= 20, f"Attendu au moins 20 combinés M2, obtenu {len(m2_combos)}"
assert m2_summary.get("default_stake") == 3.0, f"Mise attendue 3.0€, obtenu {m2_summary.get('default_stake')}"
assert m2_summary.get("won") + m2_summary.get("lost") == m2_summary.get("decided_combos"), "Won + Lost mismatch M2"
assert m2_summary.get("decided_combos") + m2_summary.get("live") + m2_summary.get("upcoming") == len(m2_combos), "Counts mismatch M2"

for c in m2_combos:
    # Cote combinée >= 2.60
    assert c["odds"] >= 2.60, f"Erreur: ticket #{c['ticket_num']} cote < 2.60 ({c['odds']})"
    # Les deux sélections sont à domicile
    m1 = c["m1"]
    m2 = c["m2"]
    assert m1.get("home"), "m1 sans équipe domicile"
    assert m2.get("home"), "m2 sans équipe domicile"
    # Cote individuelle >= 1.30 pour les tickets PENDING (les terminés conservent leur cote d'origine)
    if c.get("ticket_status") == "PENDING":
        assert float(m1.get("odds", 0)) >= 1.30, f"m1 cote < 1.30 ({m1.get('odds')}) sur ticket #{c['ticket_num']}"
        assert float(m2.get("odds", 0)) >= 1.30, f"m2 cote < 1.30 ({m2.get('odds')}) sur ticket #{c['ticket_num']}"
    assert c["ticket_status"] in ["WON", "LOST", "LIVE", "PENDING"]
    if c["ticket_status"] == "WON":
        assert c["profit_eur"] > 0, f"Ticket WON avec profit <= 0: {c['profit_eur']}"
    elif c["ticket_status"] == "LOST":
        assert c["profit_eur"] == -3.0, f"Ticket LOST avec profit != -3.0: {c['profit_eur']}"

# 2. Non-régression absolue Méthode 1
m1_combos = d.get("combos_today", [])
m1_summary = d.get("combos_summary", {})

assert len(m1_combos) >= 35, f"Attendu >= 35 combinés M1, obtenu {len(m1_combos)}"
assert m1_summary.get("won") == 19, f"M1 won attendu 19, obtenu {m1_summary.get('won')}"
assert m1_summary.get("lost") == 16, f"M1 lost attendu 16, obtenu {m1_summary.get('lost')}"
assert m1_summary.get("profit_eur") == 26.04, f"M1 profit attendu 26.04, obtenu {m1_summary.get('profit_eur')}"

print("✅ TOUS LES TESTS ASSERTIONS MÉTHODE 2 & NON-RÉGRESSION MÉTHODE 1 PASSENT AVEC SUCCÈS (100% Validé) !")
