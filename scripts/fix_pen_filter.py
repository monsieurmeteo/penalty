lines = open("scripts/auto_premium_unibet.py", encoding="utf-8").readlines()
old = lines[658]
new = old.replace('pen_per_match", 0) > 0', 'ref_name", "Inconnu") != "Inconnu"')
lines[658] = new
open("scripts/auto_premium_unibet.py", "w", encoding="utf-8").writelines(lines)
lines2 = open("scripts/auto_premium_unibet.py", encoding="utf-8").readlines()
print("Line 659:", lines2[658].rstrip())
