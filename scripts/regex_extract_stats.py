import re

with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Extract all quotes / strings
strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text)
print(f"Extracted {len(strings)} strings from payload:")

for s in strings:
    s_clean = s.replace('\\"', '"').replace('\\n', ' ')
    if any(k in s_clean.lower() for k in ['but', 'carton', 'victoire', 'marque', 'over', 'btts', '%', 'domicile', 'extérieur', 'matchs joués', 'moy.']):
        print("  STAT:", s_clean)
