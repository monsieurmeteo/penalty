import requests, json, re
from bs4 import BeautifulSoup

# Test avec un match réel ayant un SR ID connu
sr_id = "72037248"  # Pau vs Annecy
url = f"https://s5.sir.sportradar.com/unibet/fr/match/{sr_id}"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

stream_text = ""
for s in soup.find_all('script'):
    stext = s.string or ""
    if len(stext) > 10000 and "streamController" in stext:
        stream_text = stext
        break

print(f"Stream text length: {len(stream_text)}")

# Test each regex pattern
tests = [
    # Patterns for BTTS %
    (r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Deux', "BTTS v1"),
    (r'"(\d{1,3})"\s*,\s*"(?:Deux|Les deux)', "BTTS v2"),
    (r'bothTeamsScore[^,]*,\s*"(\d+)"', "BTTS bothTeamsScore"),
    (r'percentage[^,]*(\d{1,3})', "percentage generic"),
    # Patterns for Over 2.5
    (r'(\d{1,3})%\s*(?:\\\\")?\s*,\s*(?:\\\\")?Plus de 2\.5', "Over2.5 v1"),
    (r'"(\d{1,3})"\s*,\s*"(?:Plus de 2\.5|over25)', "Over2.5 v2"),
    (r'over_2_5[^,]*,\s*"(\d+)"', "over_2_5 key"),
    # Patterns for avg goals
    (r'(\d+\.\d{1,2})\s*(?:\\\\")?\s*,\s*(?:\\\\")?Total de Buts', "Goals v1"),
    (r'"avgGoals[^"]*":\s*"?(\d+\.\d+)', "avgGoals key"),
    (r'averageGoals[^,]*(\d+\.\d+)', "averageGoals key"),
]

for pattern, name in tests:
    matches = re.findall(pattern, stream_text, re.IGNORECASE)
    status = "✅ FOUND" if matches else "❌ not found"
    print(f"  [{status}] {name}: {matches[:3] if matches else ''}")

# Print raw surrounding context for any number patterns near keywords
print("\n=== RAW CONTEXT SEARCH ===")
for kw in ['winRate', 'bttsPercentage', 'goalsPerMatch', 'avgGoal', 'scoringPercentage', 'bothTeams']:
    found = re.findall(rf'.{{0,20}}{kw}.{{0,50}}', stream_text, re.IGNORECASE)
    if found:
        print(f"Keyword '{kw}': {found[:2]}")
