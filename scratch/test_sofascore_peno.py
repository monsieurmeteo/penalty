import requests

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def test_sofascore(team_name):
    r = requests.get(f'https://api.sofascore.com/api/v1/search/all?q={team_name}', headers=headers, timeout=5)
    print(f"Search status for {team_name}: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        teams = [x for x in data.get('results', []) if x.get('type') == 'team']
        if teams:
            t_entity = teams[0]['entity']
            t_id = t_entity['id']
            t_name = t_entity['name']
            print(f"  Team found: {t_name} (ID: {t_id})")
            
            r_ev = requests.get(f"https://api.sofascore.com/api/v1/team/{t_id}/events/last/0", headers=headers, timeout=5)
            print(f"  Events status: {r_ev.status_code}")
            if r_ev.status_code == 200:
                events = r_ev.json().get('events', [])
                print(f"  Recent events count: {len(events)}")
                pen_count = 0
                for ev in events[:10]:
                    ev_id = ev.get('id')
                    r_inc = requests.get(f"https://api.sofascore.com/api/v1/event/{ev_id}/incidents", headers=headers, timeout=5)
                    if r_inc.status_code == 200:
                        incidents = r_inc.json().get('incidents', [])
                        for inc in incidents:
                            inc_type = inc.get('incidentType', '')
                            if inc_type in ['penalty', 'penalty_missed', 'inGamePenalty']:
                                pen_count += 1
                print(f"  Total Penalties in 10m for {t_name}: {pen_count}")
                return pen_count
    return None

test_sofascore("Bodø/Glimt")
test_sofascore("Lyon")
