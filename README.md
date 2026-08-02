# ⚽ Premium Football Scanner (Penalty & Over 2.5)

This repository contains the automated scanner for football matches on 1XBET targeting:
- **Strategy 3 (YouTube)**: Exact Score 2-2 <= 10.00
- **Strategy 4 (Cote Directe)**: Over 2.5 <= 1.87
- **Strategy 8 (Penalty)**: Penalty Accordé OUI <= 2.90

## Structure
- `matches_input.txt`: List of matches to scan.
- `scripts/auto_premium_1xbet.py`: Main python scanner.
- `.github/workflows/premium_football_automation.yml`: GitHub Actions workflow running daily at 10:00 AM UTC.

## Local Usage
```bash
pip install curl_cffi requests
python scripts/auto_premium_1xbet.py
```
