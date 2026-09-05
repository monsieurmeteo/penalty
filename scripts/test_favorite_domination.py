import sys, os
from datetime import datetime, timezone, timedelta

# ponytail: Runnable self-check test for Favorite Win & 2 Goals Lead strategy
def evaluate_favorite_domination(m):
    c1, c2 = m.get('c1'), m.get('c2')
    if not c1 or not c2 or c1 <= 1.0 or c2 <= 1.0 or c1 == c2:
        return None

    is_dom = c1 < c2
    fav_odds = c1 if is_dom else c2
    dog_odds = c2 if is_dom else c1

    # ponytail: cote max favori 2.20 pour garantir un avantage reel cote bookmaker
    if fav_odds > 2.20:
        return None

    fav_team = m['dom'] if is_dom else m['ext']
    dog_team = m['ext'] if is_dom else m['dom']
    fav_side = 'dom' if is_dom else 'ext'

    rec_h = m.get('recent_h_dom', [])
    rec_a = m.get('recent_a_ext', [])
    fav_matches = rec_h if is_dom else rec_a
    dog_matches = rec_a if is_dom else rec_h

    if not fav_matches and not dog_matches:
        return None

    fav_wins, fav_lead2, fav_success, fav_cs = 0, 0, 0, 0
    fav_gf_tot, fav_ga_tot = 0, 0
    for match in fav_matches:
        gf = int(match.get('homeGoals', match.get('homeGoalsFt', 0)) if is_dom else match.get('awayGoals', match.get('awayGoalsFt', 0)))
        ga = int(match.get('awayGoals', match.get('awayGoalsFt', 0)) if is_dom else match.get('homeGoals', match.get('homeGoalsFt', 0)))
        gf_ht = int(match.get('homeGoalsHt', 0) if is_dom else match.get('awayGoalsHt', 0))
        ga_ht = int(match.get('awayGoalsHt', 0) if is_dom else match.get('homeGoalsHt', 0))

        win = (gf > ga) or (match.get('res') == 'W')
        lead2 = (gf - ga >= 2) or (gf_ht - ga_ht >= 2)
        if win: fav_wins += 1
        if lead2: fav_lead2 += 1
        if win or lead2: fav_success += 1
        if ga == 0: fav_cs += 1
        fav_gf_tot += gf
        fav_ga_tot += ga

    n_fav = len(fav_matches) or 1
    pct_fav_win = round(fav_wins / n_fav * 100)
    pct_fav_lead2 = round(fav_lead2 / n_fav * 100)
    pct_fav_success = round(fav_success / n_fav * 100)
    pct_fav_cs = round(fav_cs / n_fav * 100)
    avg_fav_gf = round(fav_gf_tot / n_fav, 2)
    avg_fav_ga = round(fav_ga_tot / n_fav, 2)

    dog_losses, dog_trailed2, dog_no_goal = 0, 0, 0
    dog_gf_tot, dog_ga_tot = 0, 0
    for match in dog_matches:
        gf = int(match.get('awayGoals', match.get('awayGoalsFt', 0)) if is_dom else match.get('homeGoals', match.get('homeGoalsFt', 0)))
        ga = int(match.get('homeGoals', match.get('homeGoalsFt', 0)) if is_dom else match.get('awayGoals', match.get('awayGoalsFt', 0)))
        gf_ht = int(match.get('awayGoalsHt', 0) if is_dom else match.get('homeGoalsHt', 0))
        ga_ht = int(match.get('homeGoalsHt', 0) if is_dom else match.get('awayGoalsHt', 0))

        loss = (ga > gf) or (match.get('res') == 'L')
        trailed2 = (ga - gf >= 2) or (ga_ht - gf_ht >= 2)
        if loss: dog_losses += 1
        if trailed2: dog_trailed2 += 1
        if gf == 0: dog_no_goal += 1
        dog_gf_tot += gf
        dog_ga_tot += ga

    n_dog = len(dog_matches) or 1
    pct_dog_loss = round(dog_losses / n_dog * 100)
    pct_dog_trailed2 = round(dog_trailed2 / n_dog * 100)
    pct_dog_no_goal = round(dog_no_goal / n_dog * 100)
    avg_dog_gf = round(dog_gf_tot / n_dog, 2)
    avg_dog_ga = round(dog_ga_tot / n_dog, 2)

    pts_fav = min(40, round((pct_fav_success * 0.35) + (pct_fav_cs * 0.05)))
    pts_dog = min(25, round((pct_dog_trailed2 * 0.15) + (pct_dog_loss * 0.10)))
    diff_goals = (avg_fav_gf - avg_fav_ga) + (avg_dog_ga - avg_dog_gf)
    pts_goals = max(0, min(20, round(10 + diff_goals * 3.5)))
    implied_prob = (1.0 / fav_odds) if fav_odds > 0 else 0
    pts_odds = min(15, round(implied_prob * 18))

    total_score = min(100, pts_fav + pts_dog + pts_goals + pts_odds)

    if total_score >= 85:
        badge = '💎 PLATINE'
        classe = 'Ultra-Dominateur (Break quasi garanti)'
    elif total_score >= 75:
        badge = '🥇 OR'
        classe = 'Très Solide (Forte probabilité 2 buts avance)'
    elif total_score >= 65:
        badge = '🥈 ARGENT'
        classe = 'Supérieur (Avantage net)'
    else:
        badge = '⚠️ RISQUÉ'
        classe = 'Incertain (Historique mitigé)'

    return {
        'fav_team': fav_team,
        'dog_team': dog_team,
        'fav_side': fav_side,
        'fav_odds': fav_odds,
        'dog_odds': dog_odds,
        'fav_score': total_score,
        'fav_badge': badge,
        'fav_classe': classe,
        'pct_fav_win': pct_fav_win,
        'pct_fav_lead2': pct_fav_lead2,
        'pct_fav_success': pct_fav_success,
        'pct_fav_cs': pct_fav_cs,
        'pct_dog_loss': pct_dog_loss,
        'pct_dog_trailed2': pct_dog_trailed2,
        'pct_dog_no_goal': pct_dog_no_goal,
        'avg_fav_gf': avg_fav_gf,
        'avg_dog_ga': avg_dog_ga,
        'n_fav': n_fav,
        'n_dog': n_dog,
    }

def test_favorite_domination_all():
    m1 = {
        'dom': 'Real Madrid', 'ext': 'Alaves', 'c1': 1.25, 'c2': 11.0,
        'dt_obj': datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc),
        'recent_h_dom': [{'homeGoals': 3, 'awayGoals': 0, 'homeGoalsHt': 1, 'awayGoalsHt': 0, 'res': 'W'}] * 8 + [{'homeGoals': 2, 'awayGoals': 1, 'homeGoalsHt': 2, 'awayGoalsHt': 0, 'res': 'W'}] * 2,
        'recent_a_ext': [{'homeGoals': 2, 'awayGoals': 0, 'homeGoalsHt': 1, 'awayGoalsHt': 0, 'res': 'L'}] * 7 + [{'homeGoals': 1, 'awayGoals': 1, 'homeGoalsHt': 0, 'awayGoalsHt': 0, 'res': 'D'}] * 3
    }
    r1 = evaluate_favorite_domination(m1)
    assert r1 is not None
    assert r1['fav_team'] == 'Real Madrid'
    assert r1['fav_side'] == 'dom'
    assert r1['fav_score'] >= 85
    assert r1['fav_badge'] == '💎 PLATINE'
    assert r1['pct_fav_success'] == 100

    m2 = {
        'dom': 'Bochum', 'ext': 'Bayern Munich', 'c1': 8.50, 'c2': 1.35,
        'dt_obj': datetime(2026, 9, 6, 15, 30, tzinfo=timezone.utc),
        'recent_h_dom': [{'homeGoals': 0, 'awayGoals': 2, 'homeGoalsHt': 0, 'awayGoalsHt': 1, 'res': 'L'}] * 6 + [{'homeGoals': 1, 'awayGoals': 1, 'homeGoalsHt': 0, 'awayGoalsHt': 0, 'res': 'D'}] * 4,
        'recent_a_ext': [{'homeGoals': 0, 'awayGoals': 3, 'homeGoalsHt': 0, 'awayGoalsHt': 2, 'res': 'W'}] * 7 + [{'homeGoals': 1, 'awayGoals': 2, 'homeGoalsHt': 0, 'awayGoalsHt': 1, 'res': 'W'}] * 3
    }
    r2 = evaluate_favorite_domination(m2)
    assert r2 is not None
    assert r2['fav_team'] == 'Bayern Munich'
    assert r2['fav_side'] == 'ext'
    assert r2['fav_score'] >= 80
    assert r2['pct_fav_success'] == 100

    m3 = {'dom': 'Lens', 'ext': 'Rennes', 'c1': 2.35, 'c2': 3.10}
    assert evaluate_favorite_domination(m3) is None

    m4 = {'dom': 'Nantes', 'ext': 'Angers', 'c1': 2.50, 'c2': 2.50}
    assert evaluate_favorite_domination(m4) is None

    # Tri chronologique croissant
    m1['fav_info'] = r1
    m2['fav_info'] = r2
    matches = [m1, m2]
    matches_sorted = sorted(matches, key=lambda x: x['dt_obj'])
    assert matches_sorted[0]['dom'] == 'Bochum'
    assert matches_sorted[1]['dom'] == 'Real Madrid'

    print('ALL TESTS PASSED!')

if __name__ == '__main__':
    test_favorite_domination_all()
