import re

with open("C:/Users/grego/Documents/DEV_DIVERS/penalty/scripts/sr_stream_payload.txt", "r", encoding="utf-8") as f:
    text = f.read()

print("Searching for percentages and goals in payload...")

# Find all occurrences of % with surrounding 50 characters
for m in re.finditer(r'.{0,40}\d+%.{0,40}', text):
    print("PCT MATCH:", m.group(0))

# Find occurrences of 'Deux' or 'Plus' or 'Cartons'
for m in re.finditer(r'.{0,30}(?:Deux|Plus|Cartons|buts|victoire).{0,30}', text, re.IGNORECASE):
    print("KEYWORD MATCH:", m.group(0))
