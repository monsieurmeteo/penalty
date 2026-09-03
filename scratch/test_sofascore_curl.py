from curl_cffi import requests as cf_requests

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def get_sofascore_penalties_10m(team_name):
    try:
        r = cf_requests.get(f"https://api.sofascore.com/api/v1/search/all?q={team_name}", impersonate="chrome120", headers=headers, timeout=6)
        if r.status_code == 200:
            data = r.json()
            teams = [x for x in data.get("results", []) if x.get("type") == "team"]
            if teams:
                t_entity = teams[0]["entity"]
                t_id = t_entity["id"]
                t_name = t_entity["name"]
                
                r_ev = cf_requests.get(f"https://api.sofascore.com/api/v1/team/{t_id}/events/last/0", impersonate="chrome120", headers=headers, timeout=6)
                if r_ev.status_code == 200:
                    events = r_ev.json().get("events", [])
                    pen_count = 0
                    for ev in events[:10]:
                        ev_id = ev.get("id")
                        r_inc = cf_requests.get(f"https://api.sofascore.com/api/v1/event/{ev_id}/incidents", impersonate="chrome120", headers=headers, timeout=4)
                        if r_inc.status_code == 200:
                            incidents = r_inc.json().get("incidents", [])
                            for inc in incidents:
                                inc_type = inc.get("incidentType", "")
                                if inc_type in ["penalty", "penalty_missed", "inGamePenalty"]:
                                    pen_count += 1
                    return pen_count, t_name
    except Exception as e:
        print(f"Error for {team_name}: {e}")
    return 2, team_name  # Fallback 2 default

p_bod, name_bod = get_sofascore_penalties_10m("Bodø/Glimt")
print(f"{name_bod} -> 10m Penalties: {p_bod}")

p_lyon, name_lyon = get_sofascore_penalties_10m("Lyon")
print(f"{name_lyon} -> 10m Penalties: {p_lyon}")
