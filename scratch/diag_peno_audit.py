import os, sys, json
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts'))

from analyze import analyze_pure_stats_20

# Let's inspect backtest_ledger.json or run a batch scan
with open('backtest_ledger.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total matches in ledger: {len(data)}")
pen_count = 0
for m in data:
    sp = m['scores'].get('penalty', 0)
    ref = m.get('referee', '')
    print(f"Match: {m['match']} | ScorePen: {sp} | Ref: {ref}")
    if sp >= 55:
        pen_count += 1

print(f"\nMatches with ScorePen >= 55: {pen_count}")
