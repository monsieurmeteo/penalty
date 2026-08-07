import requests, json

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
}

# Dynamo Kiev Sofascore ID: 3305, Qarabag ID: 5962
teams = [("Dynamo Kiev", 3305), ("FC Qarabag", 5962)]

print("=== RECHERCHE DES VRAIS PENALTIES (10 DERNIERS MATCHS) ===")

for name, tid in teams:
    url = f"https://api.sofascore.com/api/v1/team/{tid}/events/last/0"
    r = requests.get(url, headers=H, timeout=8)
    print(f"\n--- {name} (ID: {tid}) --- Status: {r.status_code}")
    if r.status_code == 200:
        events = r.json().get('events', [])
        print(f"Matchs récupérés : {len(events[:10])}")
        
        penalties_found = []
        for ev in events[:10]:
            match_id = ev.get('id')
            h_name = ev.get('homeTeam', {}).get('name')
            a_name = ev.get('awayTeam', {}).get('name')
            start_ts = ev.get('startTimestamp')
            tourn = ev.get('tournament', {}).get('name')
            
            # Fetch match incidents
            inc_url = f"https://api.sofascore.com/api/v1/event/{match_id}/incidents"
            ir = requests.get(inc_url, headers=H, timeout=6)
            if ir.status_code == 200:
                incidents = ir.json().get('incidents', [])
                for inc in incidents:
                    itype = inc.get('incidentType')
                    is_pen = inc.get('isPenalty') or itype in ['penalty', 'penaltyScored', 'penaltyMissed']
                    if is_pen or 'penalty' in str(inc).lower():
                        player = inc.get('player', {}).get('name', 'Inconnu')
                        minute = inc.get('time')
                        pen_type = inc.get('incidentClass') or itype
                        penalties_found.append({
                            "match": f"{h_name} vs {a_name}",
                            "tournament": tourn,
                            "player": player,
                            "minute": minute,
                            "type": pen_type
                        })
        
        if penalties_found:
            print(f"Penalties trouvés pour {name} : {len(penalties_found)}")
            for p in penalties_found:
                print(f"  ⚽ Match: {p['match']} [{p['tournament']}] | Min: {p['minute']}' | Joueur: {p['player']} ({p['type']})")
        else:
            print(f"Aucun penalty sifflé lors des 10 derniers matchs de {name}.")
