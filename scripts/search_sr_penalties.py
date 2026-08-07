import re

with open("scripts/sr_stream_payload.txt", "r", encoding="utf-8") as f:
    text = f.read()

print("Searching for penalty metrics in Sportradar s5 stream payload...")

# Search for penalty keywords
matches = re.findall(r'.{0,40}(?:penalty|penalties|pénalt|pen).{0,40}', text, re.IGNORECASE)
print(f"Total penalty references found: {len(matches)}")

for m in matches[:15]:
    print("  ->", m.strip())
