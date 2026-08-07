import requests, json
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
}

url = 'https://www.unibet.fr/paris-football/france'
r = requests.get(url, headers=H)
soup = BeautifulSoup(r.text, "html.parser")
urls = list(set([a['href'] for a in soup.find_all('a', href=True) if '/paris-football/' in a['href'] and 'vs' in a['href']]))

target_url = ("https://www.unibet.fr" + urls[0]) if urls else 'https://www.unibet.fr/paris-football/argentine/d1-argentine/3362538/boca-juniors-vs-estudiantes-lp'

print("Fetching:", target_url)
r = requests.get(target_url, headers=H, timeout=10)
soup = BeautifulSoup(r.text, 'html.parser')

scripts = soup.find_all('script', type='application/json')
print(f"Found {len(scripts)} JSON scripts")

for idx, s in enumerate(scripts):
    content = s.string or ""
    if not content: continue
    try:
        data = json.loads(content)
        print(f"Script #{idx} keys:", list(data.keys()) if isinstance(data, dict) else "List")
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  Key '{k}': type={type(v)}")
                if isinstance(v, dict):
                    print(f"    Subkeys of '{k}':", list(v.keys())[:10])
    except Exception as e:
        print(f"Error script {idx}:", e)
