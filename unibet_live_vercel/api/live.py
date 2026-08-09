from http.server import BaseHTTPRequestHandler
import json, datetime, time, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

INCIDENTS_CACHE = {}
CACHE_TTL = 30  # seconds

def get_match_details(eid):
    now = time.time()
    if eid in INCIDENTS_CACHE:
        cached_time, cached_data = INCIDENTS_CACHE[eid]
        if (now - cached_time) < CACHE_TTL:
            return cached_data

    url = f"https://prod-public-api.livescore.com/v1/api/app/scoreboard/soccer/{eid}?_t={int(now*1000)}&r={uuid.uuid4().hex[:6]}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            incs_data = data.get("Incs-s", {})
            parsed_incidents = []
            cards_dom = 0
            cards_ext = 0

            for half_key in ["1", "2", "3", "4"]:
                half_list = incs_data.get(half_key, [])
                for item in half_list:
                    sub_items = item.get("Incs") or [item]
                    for sub in sub_items:
                        it = sub.get("IT")
                        min_val = str(sub.get("Min", ""))
                        pn = sub.get("Pn", "")
                        side = "dom" if sub.get("T") == 1 else "ext"

                        if it in [36, 37, 38]:
                            inc_type = "goal"
                            if it == 37: inc_type = "penalty"
                            elif it == 38: inc_type = "csc"
                            parsed_incidents.append({
                                "type": inc_type,
                                "min": min_val,
                                "player": pn,
                                "side": side
                            })
                        elif it in [43, 44, 45]:
                            card_type = "yellow" if it in [43, 44] else "red"
                            if side == "dom": cards_dom += 1
                            else: cards_ext += 1
                            if card_type == "red":
                                parsed_incidents.append({
                                    "type": "card",
                                    "card_type": "red",
                                    "min": min_val,
                                    "player": pn,
                                    "side": side
                                })

            result = (parsed_incidents, cards_dom, cards_ext)
            INCIDENTS_CACHE[eid] = (now, result)
            return result
    except Exception:
        pass
    return ([], 0, 0)

def fetch_endpoint(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            now_ms = int(time.time() * 1000)
            rand_str = uuid.uuid4().hex[:6]
            
            # Endpoint 1 : Matchs Live Dédiés (Temps Réel Ultra-Frais, Cache 0-1s)
            live_url = f"https://prod-public-api.livescore.com/v1/api/app/live/soccer/0?_t={now_ms}&r={rand_str}"
            # Endpoint 2 : Matchs de la journée (Pré-match & Général)
            date_url = f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{today_str}/0?_t={now_ms}&r={rand_str}"
            
            data_date = fetch_endpoint(date_url)
            data_live = fetch_endpoint(live_url)

            games_map = {}
            scoring_games = []

            # 1. Traitement des matchs du jour (Date)
            for stage in data_date.get("Stages", []):
                league_name = f"{stage.get('Cnm', '')} - {stage.get('Snm', '')}"
                for ev in stage.get("Events", []):
                    eid = str(ev.get("Eid", ""))
                    eps = str(ev.get("Eps", ""))
                    t1 = ev.get("T1", [{}])[0].get("Nm", "Dom")
                    t2 = ev.get("T2", [{}])[0].get("Nm", "Ext")
                    
                    tr1 = int(ev.get("Tr1", 0) or 0)
                    tr2 = int(ev.get("Tr2", 0) or 0)
                    
                    esd = str(ev.get("Esd", ""))
                    kickoff_time = ""
                    if len(esd) >= 12:
                        try:
                            dt_utc = datetime.datetime.strptime(esd[:14], "%Y%m%d%H%M%S")
                            dt_france = dt_utc + datetime.timedelta(hours=2)
                            kickoff_time = dt_france.strftime("%H:%M")
                        except Exception:
                            kickoff_time = f"{esd[8:10]}:{esd[10:12]}"

                    status_type = "LIVE"
                    minute_display = f"{eps}'"

                    if eps == "NS":
                        status_type = "PRE_MATCH"
                        minute_display = f"🕒 {kickoff_time}" if kickoff_time else "PRÉ-MATCH"
                    elif eps in ["FT", "AP", "AET"]:
                        status_type = "FINISHED"
                        minute_display = "FIN"
                    elif eps in ["HT", "HALF"]:
                        minute_display = "PAUSE"
                    elif eps in ["CANC", "POST", "DEFD"]:
                        status_type = "FINISHED"
                        minute_display = "ANNULÉ"

                    game_item = {
                        "id": eid,
                        "league": league_name,
                        "dom": t1,
                        "ext": t2,
                        "score_dom": tr1,
                        "score_ext": tr2,
                        "minute": minute_display,
                        "status_type": status_type,
                        "kickoff": kickoff_time,
                        "incidents": [],
                        "cards_dom": 0,
                        "cards_ext": 0
                    }
                    games_map[eid] = game_item

            # 2. Surcharge avec l'endpoint LIVE dédié (Bypass total du cache de la journée)
            for stage in data_live.get("Stages", []):
                for ev in stage.get("Events", []):
                    eid = str(ev.get("Eid", ""))
                    if eid in games_map:
                        eps = str(ev.get("Eps", ""))
                        tr1 = int(ev.get("Tr1", 0) or 0)
                        tr2 = int(ev.get("Tr2", 0) or 0)
                        
                        games_map[eid]["score_dom"] = tr1
                        games_map[eid]["score_ext"] = tr2
                        if eps in ["HT", "HALF"]:
                            games_map[eid]["minute"] = "PAUSE"
                        elif eps not in ["NS", "FT", "AP", "AET"]:
                            games_map[eid]["minute"] = f"{eps}'"

            games = list(games_map.values())

            for g_item in games:
                if g_item["status_type"] == "LIVE" and (g_item["score_dom"] + g_item["score_ext"] > 0):
                    scoring_games.append((g_item["id"], g_item))

            if scoring_games:
                target_games = scoring_games[:10]
                try:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = {executor.submit(get_match_details, item[0]): item[1] for item in target_games}
                        for future in as_completed(futures, timeout=1.2):
                            g_item = futures[future]
                            try:
                                incs, c_dom, c_ext = future.result()
                                g_item["incidents"] = incs
                                g_item["cards_dom"] = c_dom
                                g_item["cards_ext"] = c_ext
                            except Exception:
                                pass
                except Exception:
                    pass

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps(games).encode('utf-8'))

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
