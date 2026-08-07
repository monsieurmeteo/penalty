"""
Backtest Over 2.5 — Méthode Unibet (Signal Score 2-2 ≤ 12.00)
Source : football-data.co.uk (CSV gratuits, pas de clé API)

On ne peut PAS reproduire le filtre Score 2-2 (pas de données histo sur ce marché).
Mais on peut tester l'essentiel : est-ce que Over 2.5 ≤ 1.87 bat le marché ?

Colonnes utilisées :
  B365>2.5  = cote Bet365 Over 2.5
  B365<2.5  = cote Bet365 Under 2.5
  FTHG      = Full Time Home Goals
  FTAG      = Full Time Away Goals
"""

import io
import requests
import csv
from collections import defaultdict

# ── Ligues et saisons à tester ───────────────────────────────────────────────
# Format football-data.co.uk : mmz4281/{saison}/{code}.csv
# Saisons disponibles : 9394 → 2425
LEAGUES = {
    "Ligue 1":       "F1",
    "Premier League":"E0",
    "La Liga":       "SP1",
    "Serie A":       "I1",
    "Bundesliga":    "D1",
    "Eredivisie":    "N1",
    "Pro League":    "B1",   # Belgique
}

SEASONS = ["2122", "2223", "2324", "2425"]  # 4 saisons = ~2000 matchs par ligue

# ── Seuils (même que l'automatisation) ────────────────────────────────────────
SEUIL_O25     = 1.87   # filtre : on ne joue que si cote ≤ ce seuil
SEUIL_BTTS    = 1.75   # filtre TRIPLE (approx. via cote BTTS si dispo)
MISE_PAR_PARI = 2.0    # euros simulés par pari

def fetch_csv(league_code, season):
    url = f"https://www.football-data.co.uk/mmz4281/{season}/{league_code}.csv"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return []
        lines = r.content.decode("latin-1").splitlines()
        reader = csv.DictReader(lines)
        return list(reader)
    except Exception as e:
        print(f"  ⚠️  {league_code} {season}: {e}")
        return []

def safe_float(val):
    try:
        return float(str(val).strip().replace(",", "."))
    except Exception:
        return None

def run_backtest():
    print("=" * 65)
    print(" BACKTEST OVER 2.5 — Méthode Seuil ≤ 1.87")
    print(" Source : football-data.co.uk (Bet365 odds)")
    print("=" * 65)

    global_all   = {"n": 0, "hits": 0, "profit": 0.0}   # tous matchs
    global_filt  = {"n": 0, "hits": 0, "profit": 0.0}   # filtre ≤ SEUIL_O25
    global_dbl   = {"n": 0, "hits": 0, "profit": 0.0}   # + filtre BTTS (approx)

    league_results = {}

    for league_name, league_code in LEAGUES.items():
        league_all  = {"n": 0, "hits": 0, "profit": 0.0}
        league_filt = {"n": 0, "hits": 0, "profit": 0.0}
        rows_loaded = 0

        for season in SEASONS:
            rows = fetch_csv(league_code, season)
            if not rows:
                continue
            rows_loaded += len(rows)

            for row in rows:
                o25   = safe_float(row.get("B365>2.5") or row.get("Max>2.5") or row.get("Avg>2.5"))
                u25   = safe_float(row.get("B365<2.5") or row.get("Max<2.5") or row.get("Avg<2.5"))
                fthg  = safe_float(row.get("FTHG"))
                ftag  = safe_float(row.get("FTAG"))

                if None in (o25, fthg, ftag) or o25 <= 1.0:
                    continue

                total_goals  = fthg + ftag
                is_over25    = total_goals > 2.5

                # --- Tous matchs ---
                league_all["n"] += 1
                if is_over25:
                    league_all["hits"] += 1
                    league_all["profit"] += MISE_PAR_PARI * (o25 - 1)
                else:
                    league_all["profit"] -= MISE_PAR_PARI

                global_all["n"] += 1
                if is_over25:
                    global_all["hits"] += 1
                    global_all["profit"] += MISE_PAR_PARI * (o25 - 1)
                else:
                    global_all["profit"] -= MISE_PAR_PARI

                # --- Filtre Over 2.5 ≤ 1.87 ---
                if o25 <= SEUIL_O25:
                    league_filt["n"] += 1
                    if is_over25:
                        league_filt["hits"] += 1
                        league_filt["profit"] += MISE_PAR_PARI * (o25 - 1)
                    else:
                        league_filt["profit"] -= MISE_PAR_PARI

                    global_filt["n"] += 1
                    if is_over25:
                        global_filt["hits"] += 1
                        global_filt["profit"] += MISE_PAR_PARI * (o25 - 1)
                    else:
                        global_filt["profit"] -= MISE_PAR_PARI

                    # --- "Double" approximatif : si Under 2.5 > 2.10 (= BTTS implicite) ---
                    if u25 and u25 >= 2.10:
                        global_dbl["n"] += 1
                        if is_over25:
                            global_dbl["hits"] += 1
                            global_dbl["profit"] += MISE_PAR_PARI * (o25 - 1)
                        else:
                            global_dbl["profit"] -= MISE_PAR_PARI

        league_results[league_name] = {
            "all": league_all,
            "filt": league_filt,
            "rows": rows_loaded
        }

    # ── Affichage par ligue ────────────────────────────────────────────────────
    print(f"\n{'Ligue':<18} {'Matchs':>7} {'Taux brut':>10} {'Matchs filtrés':>15} {'Taux filtré':>12} {'ROI filtré':>11}")
    print("-" * 80)

    for name, res in league_results.items():
        a = res["all"]
        f = res["filt"]
        rate_all  = (a["hits"] / a["n"] * 100) if a["n"] else 0
        rate_filt = (f["hits"] / f["n"] * 100) if f["n"] else 0
        roi_filt  = (f["profit"] / (f["n"] * MISE_PAR_PARI) * 100) if f["n"] else 0
        print(f"{name:<18} {a['n']:>7} {rate_all:>9.1f}%  {f['n']:>14} {rate_filt:>11.1f}%  {roi_filt:>+10.1f}%")

    # ── Totaux globaux ─────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("TOTAUX GLOBAUX (toutes ligues, 4 saisons)")
    print("=" * 80)

    for label, bucket in [("Tous matchs (sans filtre)", global_all),
                          (f"Filtre Over 2.5 ≤ {SEUIL_O25}", global_filt),
                          ("+ filtre Under > 2.10 (proxy BTTS)", global_dbl)]:
        n      = bucket["n"]
        hits   = bucket["hits"]
        profit = bucket["profit"]
        if n == 0:
            continue
        rate   = hits / n * 100
        roi    = profit / (n * MISE_PAR_PARI) * 100
        investi = n * MISE_PAR_PARI
        print(f"\n  📊 {label}")
        print(f"     Matchs    : {n}")
        print(f"     Taux Over2.5 réel  : {rate:.1f}%  (seuil rentabilité à cote 1.87 : 53.5%)")
        print(f"     Investi   : {investi:.0f} €  (à {MISE_PAR_PARI}€/pari)")
        print(f"     Profit net: {profit:+.1f} €")
        print(f"     ROI       : {roi:+.1f}%")
        if roi >= 0:
            print(f"     ✅ EDGE POSITIF — la méthode bat le bookmaker sur cet échantillon !")
        else:
            print(f"     ❌ ROI négatif — le bookmaker garde l'avantage sur cet échantillon.")

    print("\n  ℹ️  Note : Score 2-2 non dispo dans les CSV historiques.")
    print("  Ce backtest teste uniquement le filtre cote Over 2.5 ≤ 1.87.")
    print("  La vraie méthode (Score 2-2 ≤ 12.00) pourrait donner un résultat différent.\n")

if __name__ == "__main__":
    run_backtest()
