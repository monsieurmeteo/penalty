import requests, json

# Test Sofascore Token 0 API for last 10 matches of any team
# E.g. search team ID for PSG or Kiev or Real Madrid
H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
    'Accept': 'application/json',
}

url_search = "https://api.sofascore.com/api/v1/search/Paris%20SG"
try:
    r = requests.get(url_search, headers=H, timeout=6)
    if r.status_code == 200:
        data = r.json()
        teams = [x for x in data.get('results', []) if x.get('type') == 'team']
        if teams:
            team_id = teams[0]['entity']['id']
            team_name = teams[0]['entity']['name']
            print(f"Team found: {team_name} (ID: {team_id})")
            
            # Fetch last 10 matches
            url_last = f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/0"
            r_last = requests.get(url_last, headers=H, timeout=6)
            if r_last.status_code == 200:
                events = r_last.json().get('events', [])
                print(f"\n=== 10 DERNIERS MATCHS DE {team_name.upper()} (TOUTES COMPÉTITIONS) ===")
                print(f"Total matchs récupérés : {len(events[:10])}")
                
                btts_count = 0
                over25_count = 0
                goals_scored = 0
                goals_conceded = 0
                
                for idx, ev in enumerate(events[:10], 1):
                    h_name = ev.get('homeTeam', {}).get('name')
                    a_name = ev.get('awayTeam', {}).get('name')
                    h_score = ev.get('homeScore', {}).get('current', 0)
                    a_score = ev.get('awayScore', {}).get('current', 0)
                    tournament = ev.get('tournament', {}).get('name', '')
                    
                    is_btts = bool(h_score > 0 and a_score > 0)
                    is_over25 = bool(h_score + a_score > 2.5)
                    if is_btts: btts_count += 1
                    if is_over25: over25_count += 1
                    
                    if h_name == team_name:
                        goals_scored += h_score
                        goals_conceded += a_score
                    else:
                        goals_scored += a_score
                        goals_conceded += h_score
                    
                    print(f"  {idx}. [{tournament[:15]}] {h_name} {h_score}-{a_score} {a_name} | BTTS: {'Oui' if is_btts else 'Non'} | Over 2.5: {'Oui' if is_over25 else 'Non'}")
                
                print(f"\n📊 BILAN SUR LES 10 DERNIERS MATCHS :")
                print(f"  - BTTS Réel : {btts_count}/10 ({btts_count*10}%)")
                print(f"  - Over 2.5 Réel : {over25_count}/10 ({over25_count*10}%)")
                print(f"  - Moyenne Buts Marqués : {goals_scored/10:.2f}/match")
                print(f"  - Moyenne Buts Encaissés : {goals_conceded/10:.2f}/match")
except Exception as e:
    print("Error:", e)
