import requests, json, re
from bs4 import BeautifulSoup

url = "https://s5.sir.sportradar.com/unibet/fr/match/73011612"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
text = r.text

# Extract exact json strings in streamController payload
matches = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text)
print("Total string tokens:", len(matches))

# Look for specific team names, numbers, form
data_dict = {}
for i, token in enumerate(matches):
    if "Dynamo" in token or "Qarabag" in token:
        print(f"Token [{i}]: {token}")
    if "bothTeamsToScore" in token or "overUnder" in token or "winRate" in token or "goalsFor" in token:
        print(f"Stat Token [{i}]: {token} -> next tokens: {matches[i+1:i+6]}")
