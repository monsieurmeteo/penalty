import json
import sys
sys.path.insert(0, '.')
from scripts.auto_premium_unibet import is_night_match

with open("docs/data.json", "r", encoding="utf-8") as f:
    d = json.load(f)

# 1. Vérification Méthode 2
m2_combos = d.get("methode2_combos", [])
m2_summary = d.get("methode2_summary", {})

assert len(m2_combos) >= 20, f"Attendu au moins 20 combinés M2, obtenu {len(m2_combos)}"
assert m2_summary.get("default_stake") == 3.0, f"Mise attendue 3.0€, obtenu {m2_summary.get('default_stake')}"
assert m2_summary.get("won") + m2_summary.get("lost") == m2_summary.get("decided_combos"), "Won + Lost mismatch M2"
# decided_combos ne comptabilise que les tickets conformes aux critères actuels (exclut les anciens tickets à cote < 3.25)
assert m2_summary.get("decided_combos") <= sum(1 for c in m2_combos if c.get("ticket_status") in ("WON", "LOST")), "Decided combos exceeds total decided"
assert m2_summary.get("total_combos") == len(m2_combos), "Total combos mismatch M2"

for c in m2_combos:
    # Les deux sélections sont à domicile
    m1 = c["m1"]
    m2 = c["m2"]
    assert m1.get("home"), "m1 sans équipe domicile"
    assert m2.get("home"), "m2 sans équipe domicile"
    # Les deux sélections sont impérativement des favoris à domicile (fav_side == 'dom' et cote dom < cote ext)
    assert m1.get("fav_side") == "dom", f"m1 non favori domicile sur ticket #{c['ticket_num']}: fav_side={m1.get('fav_side')}"
    assert m2.get("fav_side") == "dom", f"m2 non favori domicile sur ticket #{c['ticket_num']}: fav_side={m2.get('fav_side')}"
    if m1.get("away_odds"):
        assert float(m1.get("odds", 0)) < float(m1.get("away_odds")), f"m1 cote dom >= cote ext sur ticket #{c['ticket_num']}"
    if m2.get("away_odds"):
        assert float(m2.get("odds", 0)) < float(m2.get("away_odds")), f"m2 cote dom >= cote ext sur ticket #{c['ticket_num']}"
    if m1.get("fav_team"):
        assert m1.get("fav_team") != m1.get("away"), f"m1 fav_team est l'adversaire extérieur sur #{c['ticket_num']}"
    if m2.get("fav_team"):
        assert m2.get("fav_team") != m2.get("away"), f"m2 fav_team est l'adversaire extérieur sur #{c['ticket_num']}"
    # Cote combinée >= 3.50, cote individuelle >= 1.30, score >= 35 et pas de match de nuit pour les tickets PENDING
    if c.get("ticket_status") == "PENDING":
        assert c["odds"] >= 3.50, f"Erreur: ticket #{c['ticket_num']} cote < 3.50 ({c['odds']})"
        assert float(m1.get("odds", 0)) >= 1.30, f"m1 cote < 1.30 ({m1.get('odds')}) sur ticket #{c['ticket_num']}"
        assert float(m2.get("odds", 0)) >= 1.30, f"m2 cote < 1.30 ({m2.get('odds')}) sur ticket #{c['ticket_num']}"
        if m1.get("domination_score") is not None:
            assert m1.get("domination_score") >= 35, f"m1 score < 35 ({m1.get('domination_score')}) sur ticket #{c['ticket_num']}"
        if m2.get("domination_score") is not None:
            assert m2.get("domination_score") >= 35, f"m2 score < 35 ({m2.get('domination_score')}) sur ticket #{c['ticket_num']}"
        assert not is_night_match(m1), f"m1 match de nuit sur ticket M2 #{c['ticket_num']}: {m1.get('time')}"
        assert not is_night_match(m2), f"m2 match de nuit sur ticket M2 #{c['ticket_num']}: {m2.get('time')}"
    assert c["ticket_status"] in ["WON", "LOST", "LIVE", "PENDING"]
    if c["ticket_status"] == "WON":
        assert c["profit_eur"] > 0, f"Ticket WON avec profit <= 0: {c['profit_eur']}"
    elif c["ticket_status"] == "LOST":
        assert c["profit_eur"] == -3.0, f"Ticket LOST avec profit != -3.0: {c['profit_eur']}"

# 2. Non-régression absolue Méthode 1
m1_combos = d.get("combos_today", [])
m1_summary = d.get("combos_summary", {})

assert len(m1_combos) >= 35, f"Attendu >= 35 combinés M1, obtenu {len(m1_combos)}"
assert m1_summary.get("won") >= 19, f"M1 won attendu >= 19, obtenu {m1_summary.get('won')}"
assert m1_summary.get("lost") >= 16, f"M1 lost attendu >= 16, obtenu {m1_summary.get('lost')}"
assert m1_summary.get("decided_combos") == m1_summary.get("won") + m1_summary.get("lost"), "M1 won + lost mismatch"

for c in m1_combos:
    if c.get("ticket_status") == "PENDING":
        m1 = c["m1"]
        m2 = c["m2"]
        assert not is_night_match(m1), f"m1 match de nuit sur ticket M1 #{c['ticket_num']}: {m1.get('time')}"
        assert not is_night_match(m2), f"m2 match de nuit sur ticket M1 #{c['ticket_num']}: {m2.get('time')}"

print("✅ TOUS LES TESTS ASSERTIONS MÉTHODE 2 & NON-RÉGRESSION MÉTHODE 1 PASSENT AVEC SUCCÈS (100% Validé) !")
