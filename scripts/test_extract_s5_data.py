import requests, json, re
from bs4 import BeautifulSoup

url = "https://s5.sir.sportradar.com/unibet/fr/match/3368115"
H = {'User-Agent': 'Mozilla/5.0'}

r = requests.get(url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

scripts = soup.find_all('script')
for s in scripts:
    stext = s.string or ""
    if "__reactRouterContext.streamController.enqueue" in stext:
        print("Found streamController script! Length:", len(stext))
        # search for stats keywords in stream text
        for kw in ['boca', 'estudiantes', 'but', 'victoire', 'carton', 'buteur', 'over', 'under', 'home', 'away', 'goals', 'win']:
            count = len(re.findall(kw, stext, re.IGNORECASE))
            if count > 0:
                print(f"  Keyword '{kw}': {count} occurrences")
        # print snippet
        print("\nSnippet of streamController data:\n", stext[200:1500])
