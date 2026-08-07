import requests, json, re
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.unibet.fr/paris-football',
}

def parse_sr_match_stats(sr_id):
    if not sr_id: return None
    url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}"
    try:
        r = requests.get(url, headers=H, timeout=8)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.text, 'html.parser')
        for s in soup.find_all('script'):
            stext = s.string or ""
            if len(stext) > 10000 and "streamController" in stext:
                # Extract percentages and numbers using seroval stream markers
                # Look for numbers in json stream
                numbers = [float(x) for x in re.findall(r'\"(\d+(?:\.\d+)?)\"', stext) if 0 <= float(x) <= 100]
                
                # Extract BTTS % matches
                btts_matches = [int(x) for x in re.findall(r'\"(\d{1,3})%\".*?Deux', stext, re.IGNORECASE)]
                o25_matches = [int(x) for x in re.findall(r'\"(\d{1,3})%\".*?Plus de 2\.5', stext, re.IGNORECASE)]
                goals_matches = [float(x) for x in re.findall(r'\"(\d+\.\d{1,2})\".*?Moyenne', stext, re.IGNORECASE)]
                
                btts_pct = sum(btts_matches[:2])/len(btts_matches[:2]) if btts_matches else 55.0
                o25_pct = sum(o25_matches[:2])/len(o25_matches[:2]) if o25_matches else 50.0
                avg_goals = sum(goals_matches[:4])/len(goals_matches[:4]) if goals_matches else 2.65
                
                conf_score = round(btts_pct * 0.40 + o25_pct * 0.40 + min(avg_goals / 3.0, 1.0) * 20)
                conf_score = max(10, min(99, conf_score))
                
                is_trap = bool(btts_pct < 50.0 or avg_goals < 2.30)
                
                return {
                    "btts_real_pct": round(btts_pct),
                    "o25_real_pct": round(o25_pct),
                    "avg_goals": round(avg_goals, 2),
                    "conf_score": conf_score,
                    "is_trap": is_trap
                }
    except Exception as e:
        print("SR Stats error:", e)
    return None

# Test on 3 matches
for sr_id in ["72037248", "72037242", "72037238"]:
    res = parse_sr_match_stats(sr_id)
    print(f"SR ID {sr_id} -> Stats:", res)
