import sys, os, time, datetime, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests

PORT = 8090
INCIDENTS_CACHE = {}
CACHE_TTL = 30

def get_match_details(eid):
    now = time.time()
    if eid in INCIDENTS_CACHE:
        cached_time, cached_data = INCIDENTS_CACHE[eid]
        if (now - cached_time) < CACHE_TTL:
            return cached_data

    url = f"https://prod-public-api.livescore.com/v1/api/app/scoreboard/soccer/{eid}?_t={int(now*1000)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            data = r.json()
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

def fetch_livescore_data():
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    now_ms = int(time.time() * 1000)
    ls_url = f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{today_str}/0?_t={now_ms}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }
    
    r = requests.get(ls_url, headers=headers, timeout=5)
    if r.status_code != 200:
        return []

    data = r.json()
    games = []
    scoring_games = []

    for stage in data.get("Stages", []):
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

            if status_type == "LIVE" and (tr1 + tr2 > 0):
                scoring_games.append((eid, game_item))
            
            games.append(game_item)

    if scoring_games:
        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = {executor.submit(get_match_details, item[0]): item[1] for item in scoring_games}
            for future, g_item in futures.items():
                try:
                    incs, c_dom, c_ext = future.result()
                    g_item["incidents"] = incs
                    g_item["cards_dom"] = c_dom
                    g_item["cards_ext"] = c_ext
                except Exception:
                    pass

    return games

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

class LiveStreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/live'):
            data = fetch_livescore_data()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        else:
            index_path = os.path.join(os.path.dirname(__file__), "..", "unibet_live_vercel", "public", "index.html")
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))

if __name__ == '__main__':
    server = ThreadedHTTPServer(('0.0.0.0', PORT), LiveStreamHandler)
    print(f"⚡ Serveur Live Score running on http://localhost:{PORT}")
    server.serve_forever()
