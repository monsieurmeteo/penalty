import json, re

with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Extract content inside enqueue("...")
match = re.search(r'enqueue\("(.*?)"\);', text, re.DOTALL)
if not match:
    match = re.search(r'enqueue\((.*?)\);', text, re.DOTALL)

if match:
    raw = match.group(1)
    print("Extracted enqueue content len:", len(raw))
    # Unescape JSON string
    try:
        data = json.loads(raw)
        print("Successfully parsed JSON! Type:", type(data), "len:", len(data))
        # Search for stats numbers or strings
        for item in data:
            if isinstance(item, str) and any(k in item.lower() for k in ['but', 'carton', 'victoire', 'match', 'marque', 'over', 'btts', '%']):
                print("  Stat string:", item)
            elif isinstance(item, dict):
                print("  Dict keys:", list(item.keys())[:10])
    except Exception as e:
        print("JSON parse error:", e)
        # Search directly in raw text for stats patterns
        for term in ['Pau', 'Annecy', 'goals', 'win', 'yellowCards', 'over25', 'bothTeamsToScore']:
            found = re.findall(rf'"{term}"\s*:\s*[^,}}]+', raw, re.IGNORECASE)
            if found:
                print(f"Key '{term}':", found[:5])
