import re, json

with open("scripts/extract_dynamo_qarabag_stats.py", "r", encoding="utf-8") as f:
    pass

import requests
url = "https://s5.sir.sportradar.com/unibet/fr/match/73011612"
H = {'User-Agent': 'Mozilla/5.0'}
text = requests.get(url, headers=H).text

# Find all JSON object strings or arrays in text
print("Searching for team names and form in raw stream text...")

# Print snippets containing 'Dynamo' or 'Qarabag' or goals/form
for m in re.finditer(r'.{0,50}(?:Dynamo|Qarabag|qarabag|kiev|Europa).{0,100}', text, re.IGNORECASE):
    print("SNIPPET:", m.group(0))
