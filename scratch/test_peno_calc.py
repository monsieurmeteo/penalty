import os, sys, json
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts'))

from analyze import analyze_pure_stats_20

# Test matches from today's scan
test_matches = [
    ("Bodø/Glimt", "Saint-Gilloise"),
    ("Sturm Graz", "Fenerbahce"),
    ("Boca Juniors", "CD Recoleta"),
    ("Fluminense", "Ind. Rivadavia"),
    ("Lyon", "Sparta Prague")
]

for dom, ext in test_matches:
    res = analyze_pure_stats_20(dom, ext, is_batch=True)
    if res:
        print(f"{dom} vs {ext}: ScorePen={res.get('score_penalty')}, Ref='{res.get('ref_name')}', PenoStatus='{res.get('peno_status')}', Badge='{res.get('peno_badge')}'")
