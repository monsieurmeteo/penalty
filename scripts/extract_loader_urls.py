import requests, re

url = "https://widgets.sir.sportradar.com/07aa200103b683f08a04498c214b117b/widgetloader"
text = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text

strings = re.findall(r'["\'](https?://[^"\']+)["\']', text)
print(f"Found {len(strings)} full URLs in loader:")
for s in set(strings):
    print(" ", s)

paths = re.findall(r'["\'](/[a-zA-Z0-9_\-/\.]{3,60})["\']', text)
print(f"Found {len(paths)} relative paths:")
for p in sorted(list(set(paths)))[:30]:
    print(" ", p)
