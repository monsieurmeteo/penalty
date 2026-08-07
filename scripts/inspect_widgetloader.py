import requests, re

url = "https://widgets.sir.sportradar.com/07aa200103b683f08a04498c214b117b/widgetloader"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H)
print("Status:", r.status_code)
text = r.text

print("Loader JS length:", len(text))
urls = re.findall(r'https?://[^\s"\'\`]+', text)
print("Found URLs in loader:")
for u in set(urls):
    print(" ", u)
