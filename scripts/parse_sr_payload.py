import re, json

with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Extract json array inside enqueue(...)
match = re.search(r'enqueue\((.*?)\);?\s*$', text, re.DOTALL)
if match:
    raw_json = match.group(1)
    data = json.loads(raw_json)
    print("Parsed JSON enqueue object! Type:", type(data))
    if isinstance(data, list):
        print("List length:", len(data))
        # Find all strings in the data array that mention stats or percentages
        stats_strings = [x for x in data if isinstance(x, str)]
        print("Total strings in array:", len(stats_strings))
        for s in stats_strings:
            if any(k in s.lower() for k in ['buteur', 'but', 'victoire', 'carton', '%', 'pau', 'annecy', 'home', 'away', 'total', 'average']):
                print("  Stat string:", s[:100])
else:
    print("No enqueue match found")
