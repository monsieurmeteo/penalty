import requests
from bs4 import BeautifulSoup
import re, os

URL = "https://www.pronosoft.com/fr/parions_sport/liste-parions-sport-plein-ecran.htm"
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
}

print(f"Fetching Pronosoft matches directly from {URL}...")
try:
    r = requests.get(URL, headers=H, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    
    rows = soup.find_all("tr")
    football_matches = []
    current_sport = "football"
    
    for row in rows:
        text = row.text.lower()
        if "tennis" in text and len(text) < 40:
            current_sport = "tennis"
        elif "rugby" in text and len(text) < 40:
            current_sport = "rugby"
        elif "basket" in text and len(text) < 40:
            current_sport = "basket"
        elif "volley" in text and len(text) < 40:
            current_sport = "volley"
        elif "football" in text and len(text) < 40:
            current_sport = "football"
            
        sport_span = row.find("span", class_="sport")
        if sport_span:
            classes = " ".join(sport_span.get("class", []))
            if "football" in classes or "foot" in classes:
                current_sport = "football"
            elif "tennis" in classes:
                current_sport = "tennis"
            elif "rugby" in classes:
                current_sport = "rugby"
                
        a_tag = row.find("a", class_="infos")
        if a_tag:
            match_name = "".join(child for child in a_tag.children if isinstance(child, str)).strip()
            parts = match_name.split(" - ")
            if len(parts) == 2:
                time_tag = row.find("span", {"data-date-format": "hour"})
                time_str = time_tag.text.strip() if time_tag else "00h00"
                
                # Exclude tennis initial names (e.g. B.Nakashima - T.Fritz)
                is_tennis = re.search(r"\b[A-Z]\.[A-Z]", match_name)
                
                if current_sport == "football" and not is_tennis:
                    home, away = parts[0].strip(), parts[1].strip()
                    # Exclude generic non-match lines
                    if "paris sp" not in home.lower() and "paris sp" not in away.lower():
                        football_matches.append({
                            "time": time_str,
                            "home": home,
                            "away": away
                        })

    print(f"Parsed ALL {len(football_matches)} football matches from Pronosoft.")
    
    output_path = "matches_input.txt"
    by_time = {}
    for m in football_matches:
        by_time.setdefault(m["time"], []).append(m)
        
    with open(output_path, "w", encoding="utf-8") as f:
        for t, list_m in sorted(by_time.items()):
            f.write(f"{t}\n")
            for m in list_m:
                f.write(f"{m['home']} - {m['away']}\n")
                
    print(f"Successfully saved {len(football_matches)} matches to {output_path}")

except Exception as e:
    print(f"Error parsing Pronosoft: {e}")
