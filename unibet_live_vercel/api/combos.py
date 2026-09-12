from http.server import BaseHTTPRequestHandler
import json, time, urllib.request, uuid

RAW_URL = "https://raw.githubusercontent.com/mto-user84925/penalty/master/docs/data.json"
PAGES_URL = "https://mto-user84925.github.io/penalty/data.json"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        content = b"{}"
        now_ms = int(time.time() * 1000)
        rand_str = uuid.uuid4().hex[:6]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
        
        urls = [
            f"{RAW_URL}?_t={now_ms}&r={rand_str}",
            f"{PAGES_URL}?_t={now_ms}"
        ]
        
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    if resp.status == 200:
                        raw_data = resp.read()
                        # Sanity check valid json
                        json.loads(raw_data.decode("utf-8"))
                        content = raw_data
                        break
            except Exception:
                continue

        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        self.wfile.write(content)
