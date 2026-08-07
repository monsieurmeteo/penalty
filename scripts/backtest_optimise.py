"""
Backtest étendu — cherche la combinaison de filtres qui bat le marché
Hypothèses testées :
  1. Restriction à certaines ligues (les meilleures du backtest précédent)
  2. Plage de cote plus stricte (1.60-1.82 au lieu de ≤1.87)
  3. Under 2.5 très haut (≥ 2.20) = bookmaker très confiant Over
  4. Combinaisons
"""

import requests, csv

LEAGUES = {
    "Ligue 1":       "F1",
    "Premier League":"E0",
    "La Liga":       "SP1",
    "Serie A":       "I1",
    "Bundesliga":    "D1",
    "Eredivisie":    "N1",
    "Pro League":    "B1",
}
SEASONS = ["2122", "2223", "2324", "2425"]
MISE = 2.0

def fetch_csv(code, season):
    url = f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return []
        lines = r.content.decode("latin-1").splitlines()
        return list(csv.DictReader(lines))
    except:
        return []

def sf(v):
    try: return float(str(v).strip().replace(",", "."))
    except: return None

# Collecte toutes les données
all_rows = []
for league_name, code in LEAGUES.items():
    for season in SEASONS:
        for row in fetch_csv(code, season):
            o25  = sf(row.get("B365>2.5") or row.get("Max>2.5"))
            u25  = sf(row.get("B365<2.5") or row.get("Max<2.5"))
            fthg = sf(row.get("FTHG"))
            ftag = sf(row.get("FTAG"))
            if None in (o25, fthg, ftag) or o25 <= 1.0: continue
            all_rows.append({
                "league": league_name,
                "o25": o25,
                "u25": u25,
                "over": (fthg + ftag) > 2.5,
            })

print(f"✅ {len(all_rows)} matchs chargés\n")

def test_filter(label, rows):
    n = len(rows)
    if n < 50: return
    hits = sum(1 for r in rows if r["over"])
    profit = sum((r["o25"]-1)*MISE if r["over"] else -MISE for r in rows)
    rate = hits/n*100
    roi = profit/(n*MISE)*100
    investi = n*MISE
    flag = "✅ EDGE !" if roi >= 0 else ("🟡 proche" if roi >= -1.5 else "❌")
    print(f"  {flag} {label}")
    print(f"     {n} matchs | Taux: {rate:.1f}% | ROI: {roi:+.1f}% | P&L: {profit:+.0f}€ sur {investi:.0f}€ investis")

print("=" * 70)
print(" RECHERCHE DU FILTRE GAGNANT")
print("=" * 70)

# ── Test 1 : baseline ≤1.87 ──────────────────────────────────────────────────
print("\n📌 BASELINE (référence)")
test_filter("Over 2.5 ≤ 1.87 (toutes ligues)",
    [r for r in all_rows if r["o25"] <= 1.87])

# ── Test 2 : plages de cotes ─────────────────────────────────────────────────
print("\n📌 PLAGES DE COTES (toutes ligues)")
for lo, hi in [(1.50,1.65),(1.65,1.75),(1.75,1.82),(1.82,1.87),(1.87,1.95)]:
    test_filter(f"Over 2.5 entre {lo} et {hi}",
        [r for r in all_rows if lo <= r["o25"] <= hi])

# ── Test 3 : filtre Under 2.5 ────────────────────────────────────────────────
print("\n📌 FILTRE UNDER 2.5 (confiance bookmaker, toutes ligues, Over ≤1.87)")
base = [r for r in all_rows if r["o25"] <= 1.87 and r["u25"]]
for seuil in [2.00, 2.10, 2.15, 2.20, 2.30]:
    test_filter(f"Under 2.5 ≥ {seuil}",
        [r for r in base if r["u25"] >= seuil])

# ── Test 4 : sélection de ligues ─────────────────────────────────────────────
print("\n📌 SÉLECTION DE LIGUES (Over ≤1.87)")
base = [r for r in all_rows if r["o25"] <= 1.87]
combos = [
    ["La Liga", "Ligue 1"],
    ["La Liga", "Ligue 1", "Premier League"],
    ["La Liga", "Ligue 1", "Bundesliga"],
    ["Bundesliga", "Eredivisie", "Premier League"],
    ["La Liga", "Ligue 1", "Premier League", "Serie A"],
]
for combo in combos:
    test_filter(f"Ligues: {', '.join(combo)}",
        [r for r in base if r["league"] in combo])

# ── Test 5 : combinaisons gagnantes ──────────────────────────────────────────
print("\n📌 COMBINAISONS (Over ≤1.87 + Under ≥2.15 + ligues sélectionnées)")
base_dbl = [r for r in all_rows if r["o25"] <= 1.87 and r["u25"] and r["u25"] >= 2.15]
for combo in [
    ["La Liga", "Ligue 1", "Premier League"],
    ["La Liga", "Ligue 1", "Bundesliga"],
    ["La Liga", "Premier League", "Serie A", "Bundesliga"],
    list(LEAGUES.keys()),  # toutes ligues
]:
    test_filter(f"Under≥2.15 + Ligues: {', '.join(combo)}",
        [r for r in base_dbl if r["league"] in combo])

# ── Test 6 : plage cote + under + ligues ─────────────────────────────────────
print("\n📌 TRIPLE FILTRE : plage cote + Under ≥2.15 + meilleures ligues")
best_leagues = ["La Liga", "Ligue 1", "Premier League", "Bundesliga"]
for lo, hi in [(1.65,1.82),(1.70,1.85),(1.60,1.80)]:
    test_filter(f"Cote [{lo}-{hi}] + Under≥2.15 + {len(best_leagues)} ligues",
        [r for r in all_rows
         if lo <= r["o25"] <= hi
         and r["u25"] and r["u25"] >= 2.15
         and r["league"] in best_leagues])

print()
