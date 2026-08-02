import requests
from bs4 import BeautifulSoup
import re, os

URL = "https://www.pronosoft.com/fr/parions_sport/liste-parions-sport-plein-ecran.htm"
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
}

print(f"Fetching Pronosoft matches from {URL}...")
try:
    # Use Jina Reader first, if forbidden fallback to direct fetch
    jina_url = f"https://r.jina.ai/{URL}"
    r = requests.get(jina_url, headers=H, timeout=15)
    
    html = ""
    if r.status_code == 200 and "Forbidden" not in r.text and "Cloudflare" not in r.text:
        print("Fetched via Jina Reader successfully.")
        # Jina returns markdown, so let's extract matches using regex
        matches = []
        current_time = "00h00"
        for line in r.text.split("\n"):
            line = line.strip()
            # Time regex (ex: **16h55**) or similar
            time_match = re.search(r"\b(\d{2}h\d{2})\b", line)
            if time_match:
                current_time = time_match.group(1)
            # Match regex: Team A - Team B
            # Ex: [sport] Team A - Team B [details]
            if " - " in line and not line.startswith("|") and not line.startswith("["):
                parts = line.split(" - ")
                if len(parts) == 2:
                    home = re.sub(r"\[.*?\]", "", parts[0]).strip()
                    away = re.sub(r"\[.*?\]", "", parts[1]).strip()
                    # Clean up bold/markdown artifacts
                    home = home.replace("*", "").replace("`", "")
                    away = away.replace("*", "").replace("`", "")
                    matches.append({"time": current_time, "home": home, "away": away})
                    
        html = "" # Skip bs4 if Jina worked
    else:
        # Fallback to direct fetch
        print("Jina blocked or failed, fetching Pronosoft directly...")
        r = requests.get(URL, headers=H, timeout=15)
        html = r.text
        
    football_matches = []
    
    if html:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.find_all("tr")
        for row in rows:
            sport_span = row.find("span", class_="sport")
            if sport_span and "football" in sport_span.get("class", []):
                time_tag = row.find("span", {"data-date-format": "hour"})
                time_str = time_tag.text.strip() if time_tag else "00h00"
                a_tag = row.find("a", class_="infos")
                if a_tag:
                    match_name = "".join(child for child in a_tag.children if isinstance(child, str)).strip()
                    parts = match_name.split(" - ")
                    if len(parts) == 2:
                        football_matches.append({
                            "time": time_str,
                            "home": parts[0].strip(),
                            "away": parts[1].strip()
                        })
    else:
        football_matches = matches

    print(f"Parsed {len(football_matches)} football matches.")
    
    # Save to matches_input.txt
    output_path = "matches_input.txt"
    by_time = {}
    for m in football_matches:
        by_time.setdefault(m["time"], []).append(m)
        
    with open(output_path, "w", encoding="utf-8") as f:
        for t, list_m in sorted(by_time.items()):
            f.write(f"{t}\n")
            for m in list_m:
                f.write(f"{m['home']} - {m['away']}\n")
                
    print(f"Successfully saved to {output_path}")

except Exception as e:
    print(f"Error parsing Pronosoft: {e}")
