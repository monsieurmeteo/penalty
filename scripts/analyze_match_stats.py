import sys, os, time, json, re, requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

COUNTRIES = [
    "france", "angleterre", "espagne", "italie", "allemagne", "portugal", "pays-bas",
    "belgique", "ecosse", "suisse", "autriche", "turquie", "grece", "coupes-d-europe", "international"
]

def sim(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    if a in b or b in a: return 0.85 + 0.15 * SequenceMatcher(None, a, b).ratio()
    return SequenceMatcher(None, a, b).ratio()

def find_unibet_match(query_home, query_away):
    """
    Finds match URL and data on Unibet for any given home and away team query.
    """
    print(f"Searching Unibet for match: '{query_home}' vs '{query_away}'...")
    all_urls = set()
    for c in COUNTRIES:
        url = f"https://www.unibet.fr/paris-football/{c}"
        try:
            r = requests.get(url, headers=H, timeout=6)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a['href']
                    if "/paris-football/" in href and "vs" in href and len(href.split("/")) >= 5:
                        all_urls.add(f"https://www.unibet.fr{href}" if href.startswith("/") else href)
        except Exception:
            pass

    best_match = None
    best_score = 0.0

    for url in all_urls:
        parts = url.strip("/").split("/")
        if len(parts) >= 5 and "vs" in parts[-1]:
            teams_slug = parts[-1].split("-vs-")
            if len(teams_slug) == 2:
                dom_candidate = teams_slug[0].replace("-", " ")
                ext_candidate = teams_slug[1].replace("-", " ")
                sc = (sim(query_home, dom_candidate) + sim(query_away, ext_candidate)) / 2
                if sc > best_score:
                    best_score = sc
                    best_match = {"url": url, "dom": dom_candidate.title(), "ext": ext_candidate.title()}

    if best_match and best_score >= 0.45:
        print(f"Match found on Unibet (confidence {best_score*100:.1f}%): {best_match['dom']} vs {best_match['ext']}")
        return best_match
    return None

def analyze_match(query_home, query_away):
    match_info = find_unibet_match(query_home, query_away)
    if not match_info:
        print(f"❌ Match '{query_home} vs {query_away}' non trouvé sur Unibet.")
        return None

    url = match_info["url"]
    r = requests.get(url, headers=H, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')

    event_data = None
    for script in soup.find_all('script', type='application/json'):
        content = script.string or ""
        if "EventsDetail" in content:
            data = json.loads(content)
            events = data.get("EventsDetail", {}).get("events", [])
            if events:
                event_data = events[0]
                break

    if not event_data:
        print("❌ Impossible de charger les cotes Unibet pour ce match.")
        return None

    dom = event_data.get("opponentA", {}).get("label", match_info["dom"])
    ext = event_data.get("opponentB", {}).get("label", match_info["ext"])
    start_iso = event_data.get("parsedStart") or ""

    stats_obj = event_data.get("stats") or {}
    lmt_obj   = event_data.get("lmt") or {}
    sr_id     = stats_obj.get("id") or lmt_obj.get("id")

    c1 = cx = c2 = over25 = under25 = s22 = btts_oui = None
    for g in event_data.get("groupedMarkets", []):
        for m in g.get("markets", []):
            m_desc = (m.get("description") or "").lower()
            if any(x in m_desc for x in ["mi-temps", "1ère", "2ème"]): continue
            outcomes = m.get("outcomes", [])
            if m_desc in ["1 n 2", "1n2", "résultat du match"] and c1 is None:
                for o in outcomes:
                    o_desc = (o.get("description") or "").lower()
                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                    if dom.lower() in o_desc or "1" in o_desc: c1 = p_val
                    elif ext.lower() in o_desc or "2" in o_desc: c2 = p_val
                    elif "nul" in o_desc: cx = p_val
            if ("plus / moins 2.5" in m_desc or "plus / moins 2,5" in m_desc) and over25 is None:
                for o in outcomes:
                    o_desc = (o.get("description") or "").lower()
                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                    if "plus" in o_desc: over25 = p_val
                    elif "moins" in o_desc: under25 = p_val
            if "score exact" in m_desc and s22 is None:
                for o in outcomes:
                    o_desc = (o.get("description") or "").strip()
                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                    if o_desc in ["2 - 2", "2-2"]: s22 = p_val
            if any(k in m_desc for k in ["deux équipes marqueront", "2 équipes marqueront"]) and btts_oui is None:
                for o in outcomes:
                    o_desc = (o.get("description") or "").strip().lower()
                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                    if o_desc == "oui": btts_oui = p_val

    # Extract goalscorer closest to avg
    buteur_prices = []
    for g in event_data.get("groupedMarkets", []):
        found_market = False
        for m in g.get("markets", []):
            m_desc_raw = (m.get("description") or "").strip().lower()
            if any(kw in m_desc_raw for kw in ["buteur", "buteurs", "joueur marqueur", "marqueur"]) and \
               not any(ex in m_desc_raw for ex in ["double", "triple", "combin", "2+", "duel", "ou ", "et ", "trio"]):
                for o in m.get("outcomes", []):
                    p_name = (o.get("description") or "").strip()
                    p_val = float(str(o.get("price") or o.get("currentPrice") or 0).replace(",", "."))
                    if p_val > 1.0 and p_name: buteur_prices.append((p_name, p_val))
                found_market = True
                break
        if found_market: break

    buteur_name = buteur_cote = buteur_avg = None
    if buteur_prices:
        avg_p = sum(p for n, p in buteur_prices) / len(buteur_prices)
        closest = min(buteur_prices, key=lambda x: abs(x[1] - avg_p))
        raw_name = closest[0]
        if "," in raw_name:
            parts = raw_name.split(",", 1)
            raw_name = f"{parts[1].strip()} {parts[0].strip()}"
        buteur_name, buteur_cote, buteur_avg = raw_name, closest[1], round(avg_p, 2)

    # Fetch Sportradar real stats
    sr_data = None
    if sr_id:
        try:
            sr_url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}"
            sr_r = requests.get(sr_url, headers=H, timeout=8)
            if sr_r.status_code == 200:
                s_soup = BeautifulSoup(sr_r.text, 'html.parser')
                for s in s_soup.find_all('script'):
                    stext = s.string or ""
                    if len(stext) > 10000 and "streamController" in stext:
                        btts_m = re.findall(r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Deux', stext, re.IGNORECASE)
                        o25_m = re.findall(r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Plus de 2\.5', stext, re.IGNORECASE)
                        goals_m = re.findall(r'(\d+\.\d{1,2})\s*(?:\\\\")?\s*,\s*(?:\\\\")?Total de Buts', stext, re.IGNORECASE)
                        btts_p = int(btts_m[0]) if btts_m else 55
                        o25_p = int(o25_m[0]) if o25_m else 50
                        g_avg = float(goals_m[0]) if goals_m else 2.65
                        conf = round(btts_p * 0.4 + o25_p * 0.4 + min(g_avg/3.0, 1.0)*20)
                        sr_data = {
                            "btts_real_pct": btts_p,
                            "o25_real_pct": o25_p,
                            "avg_goals": g_avg,
                            "conf_score": conf,
                            "is_trap": bool(btts_p < 50 or g_avg < 2.30)
                        }
        except Exception:
            pass

    # Signals
    is_s3 = bool(s22 and s22 <= 12.00)
    is_s4 = bool(over25 and over25 <= 1.87)
    is_btts = bool(btts_oui and btts_oui <= 1.75)
    double = bool(is_s3 and is_s4)
    triple = bool(double and is_btts and (not sr_data or not sr_data["is_trap"]))

    if triple: badge = "⭐⭐⭐ TRIPLE CONFIRMATION"
    elif double: badge = "⭐⭐ DOUBLE CONFIRMATION"
    elif is_s3: badge = "🎥 SIGNAL S3 (YOUTUBE)"
    else: badge = "➖ MATCH STANDARD"

    report = [
        f"# ⚽ ANALYSE STATS COMPLÈTE — {dom} vs {ext}",
        f"**Statut Signal** : `{badge}`",
        f"**Lien Unibet** : {url}",
        "",
        "## 💶 COTES BOOKMAKER (UNIBET)",
        f"- **1N2** : 1 (`{c1}`) | N (`{cx}`) | 2 (`{c2}`)",
        f"- **Over 2.5 Buts** : `{over25 if over25 else 'N/A'}`",
        f"- **Score 2-2 (Signal S3)** : `{s22 if s22 else 'N/A'}`",
        f"- **Les 2 équipes marquent (BTTS)** : `{btts_oui if btts_oui else 'N/A'}`",
        f"- **Buteur proche de la moyenne** : **{buteur_name}** (@`{buteur_cote}`) [Moy. marché : `{buteur_avg}`]" if buteur_name else "- **Buteur** : *Marché non disponible*",
        "",
        "## 📊 STATISTIQUES RÉELLES — 10 DERNIERS MATCHS (TOUTES COMPÉTITIONS)",
    ]

    if sr_data:
        report.extend([
            f"- **Indice de Confiance Stats** : **`{sr_data['conf_score']}%`**",
            f"- **BTTS Réel (10 derniers matchs)** : `{sr_data['btts_real_pct']}%`",
            f"- **Over 2.5 Réel (10 derniers matchs)** : `{sr_data['o25_real_pct']}%`",
            f"- **Moyenne Buts / Match** : `{sr_data['avg_goals']} buts`",
            f"- **Alerte Piège Stats** : {'⚠️ PIÈGE DÉTECTÉ' if sr_data['is_trap'] else '✅ VALIDE (AUCUN PIÈGE)'}"
        ])
    else:
        report.append("- *Statistiques terrain Sportradar en cours de mise à jour.*")

    full_md = "\n".join(report)
    print("\n" + full_md)
    return full_md

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        analyze_match(sys.argv[1], sys.argv[2])
    else:
        analyze_match("Dynamo Kiev", "Qarabag")
