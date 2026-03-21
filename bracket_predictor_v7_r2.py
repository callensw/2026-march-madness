#!/usr/bin/env python3
"""
March Madness 2026 ML Bracket Predictor — V7: Round 2 Update
Incorporates actual R1 results, computes R1 performance signals,
evaluates model accuracy, re-weights ensemble, and predicts R2.
"""

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

from bracket_predictor import (
    pull_supabase_data, aggregate_player_features,
    generate_synthetic_team, compute_delta_features, build_2026_features,
    train_models, predict_ensemble, write_to_supabase,
    get_hist_seed_win_rate, moneyline_to_prob, parse_record, load_historical_data,
    SUPABASE_URL, SUPABASE_KEY, EXPECTED_KENPOM, N_SIMULATIONS,
    SHARED_FEATURES, HIST_SEED_WIN_RATE, ROUND_MAP,
    CEILING_F4, CEILING_CHAMP, CEILING_WINNER,
    W_LR, W_XGB, W_VEGAS, W_AGENT, W_MC,
    vegas_prob, agent_swarm_prob, monte_carlo_prob,
)
from bracket_predictor_v6 import (
    compute_upset_features_from_teams, UPSET_FEATURES,
    generate_upset_training_data, train_upset_model,
)
from supabase import create_client

np.random.seed(42)

POWER_CONFERENCES = ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East']

# ═══════════════════════════════════════════════
# R1 ACTUAL RESULTS
# ═══════════════════════════════════════════════

R1_RESULTS = [
    # EAST (verified via web search)
    {'region': 'East', 'seed_w': 1,  'winner': 'Duke',           'seed_l': 16, 'loser': 'Siena',
     'score_w': 71, 'score_l': 65, 'notes': 'Trailed by 13 in 2nd half. Cameron Boozer 22pts 13reb.'},
    {'region': 'East', 'seed_w': 9,  'winner': 'TCU',            'seed_l': 8,  'loser': 'Ohio State',
     'score_w': 66, 'score_l': 64, 'notes': 'Xavier Edmonds game-winner 4.3 sec left.'},
    {'region': 'East', 'seed_w': 5,  'winner': "St. John's",     'seed_l': 12, 'loser': 'Northern Iowa',
     'score_w': 77, 'score_l': 53, 'notes': 'St. Johns dominated.'},
    {'region': 'East', 'seed_w': 4,  'winner': 'Kansas',         'seed_l': 13, 'loser': 'Cal Baptist',
     'score_w': 68, 'score_l': 60, 'notes': 'Led by 26 then allowed 19-2 run. Darryn Peterson 28pts.'},
    {'region': 'East', 'seed_w': 6,  'winner': 'Louisville',     'seed_l': 11, 'loser': 'USF',
     'score_w': 83, 'score_l': 79, 'notes': 'Louisville survives close game vs South Florida.'},
    {'region': 'East', 'seed_w': 3,  'winner': 'Michigan State', 'seed_l': 14, 'loser': 'North Dakota State',
     'score_w': 92, 'score_l': 67, 'notes': 'MSU dominant, 25-point win.'},
    {'region': 'East', 'seed_w': 7,  'winner': 'UCLA',           'seed_l': 10, 'loser': 'UCF',
     'score_w': 75, 'score_l': 71, 'notes': 'Eric Dailey Jr 20pts. Four double-digit scorers.'},
    {'region': 'East', 'seed_w': 2,  'winner': 'UConn',          'seed_l': 15, 'loser': 'Furman',
     'score_w': 82, 'score_l': 71, 'notes': 'Tarris Reed Jr 31pts 27reb. Shot 5-of-25 from 3.'},

    # WEST (verified via web search)
    {'region': 'West', 'seed_w': 1,  'winner': 'Arizona',        'seed_l': 16, 'loser': 'LIU',
     'score_w': 92, 'score_l': 58, 'notes': 'Arizona dominated.'},
    {'region': 'West', 'seed_w': 9,  'winner': 'Utah State',     'seed_l': 8,  'loser': 'Villanova',
     'score_w': 86, 'score_l': 76, 'notes': 'Utah State convincing 10-pt win.'},
    {'region': 'West', 'seed_w': 12, 'winner': 'High Point',     'seed_l': 5,  'loser': 'Wisconsin',
     'score_w': 83, 'score_l': 82, 'notes': 'UPSET by 1 point! High Point eliminates Wisconsin.'},
    {'region': 'West', 'seed_w': 4,  'winner': 'Arkansas',       'seed_l': 13, 'loser': 'Hawaii',
     'score_w': 97, 'score_l': 78, 'notes': 'Arkansas dominant, 19-point win.'},
    {'region': 'West', 'seed_w': 11, 'winner': 'Texas',          'seed_l': 6,  'loser': 'BYU',
     'score_w': 79, 'score_l': 71, 'notes': 'UPSET. Texas eliminates BYU.'},
    {'region': 'West', 'seed_w': 3,  'winner': 'Gonzaga',        'seed_l': 14, 'loser': 'Kennesaw State',
     'score_w': 73, 'score_l': 64, 'notes': 'Gonzaga controlled, 9-point win.'},
    {'region': 'West', 'seed_w': 7,  'winner': 'Miami FL',       'seed_l': 10, 'loser': 'Missouri',
     'score_w': 80, 'score_l': 66, 'notes': 'Malik Reneau 24pts (19 in 2nd half). 11-0 run sealed it.'},
    {'region': 'West', 'seed_w': 2,  'winner': 'Purdue',         'seed_l': 15, 'loser': 'Queens',
     'score_w': 104, 'score_l': 69, 'notes': 'Braden Smith 26pts 8ast, broke career assists record.'},

    # MIDWEST (verified via web search)
    {'region': 'Midwest', 'seed_w': 1,  'winner': 'Michigan',    'seed_l': 16, 'loser': 'Howard',
     'score_w': 101, 'score_l': 80, 'notes': 'Michigan dominant, 21-point win.'},
    {'region': 'Midwest', 'seed_w': 9,  'winner': 'Saint Louis', 'seed_l': 8,  'loser': 'Georgia',
     'score_w': 102, 'score_l': 77, 'notes': 'BLOWOUT upset. SLU dominated.'},
    {'region': 'Midwest', 'seed_w': 5,  'winner': 'Texas Tech',  'seed_l': 12, 'loser': 'Akron',
     'score_w': 91, 'score_l': 71, 'notes': 'Shot 64% from floor, 11 threes. Jaylen Petty 24pts.'},
    {'region': 'Midwest', 'seed_w': 4,  'winner': 'Alabama',     'seed_l': 13, 'loser': 'Hofstra',
     'score_w': 87, 'score_l': 69, 'notes': 'Labaron Philon 29pts 8reb 7ast. Holloway absent.'},
    {'region': 'Midwest', 'seed_w': 6,  'winner': 'Tennessee',   'seed_l': 11, 'loser': 'Miami OH',
     'score_w': 78, 'score_l': 56, 'notes': 'Defense dominated after slow start.'},
    {'region': 'Midwest', 'seed_w': 3,  'winner': 'Virginia',    'seed_l': 14, 'loser': 'Wright State',
     'score_w': 82, 'score_l': 73, 'notes': 'Virginia controlled, 9-point win.'},
    {'region': 'Midwest', 'seed_w': 7,  'winner': 'Kentucky',    'seed_l': 10, 'loser': 'Santa Clara',
     'score_w': 89, 'score_l': 84, 'notes': 'Overtime thriller. Spread was -3.5, won by 5 in OT.'},
    {'region': 'Midwest', 'seed_w': 2,  'winner': 'Iowa State',  'seed_l': 15, 'loser': 'Tennessee State',
     'score_w': 108, 'score_l': 74, 'notes': 'Dominant but raised concerns.'},

    # SOUTH (verified via web search)
    {'region': 'South', 'seed_w': 1,  'winner': 'Florida',       'seed_l': 16, 'loser': 'Prairie View A&M',
     'score_w': 114, 'score_l': 55, 'notes': 'HISTORIC 59-pt win. Led 60-21 at half. 7 in double figures. Boogie Fland 6-of-6.'},
    {'region': 'South', 'seed_w': 9,  'winner': 'Iowa',          'seed_l': 8,  'loser': 'Clemson',
     'score_w': 67, 'score_l': 61, 'notes': 'Iowa led most of game. Bennett Stirtz 16pts.'},
    {'region': 'South', 'seed_w': 5,  'winner': 'Vanderbilt',    'seed_l': 12, 'loser': 'McNeese',
     'score_w': 78, 'score_l': 68, 'notes': 'Trailed by 11 in 1st half, rallied.'},
    {'region': 'South', 'seed_w': 4,  'winner': 'Nebraska',      'seed_l': 13, 'loser': 'Troy',
     'score_w': 76, 'score_l': 47, 'notes': 'First NCAA tourney win ever for Nebraska. Dominant 29-pt win.'},
    {'region': 'South', 'seed_w': 11, 'winner': 'VCU',           'seed_l': 6,  'loser': 'UNC',
     'score_w': 82, 'score_l': 78, 'notes': 'UPSET in OT. VCU Havoc defense eliminated UNC.'},
    {'region': 'South', 'seed_w': 3,  'winner': 'Illinois',      'seed_l': 14, 'loser': 'Penn',
     'score_w': 105, 'score_l': 70, 'notes': 'Illinois dominant, 35-point win.'},
    {'region': 'South', 'seed_w': 10, 'winner': 'Texas A&M',     'seed_l': 7,  'loser': "Saint Mary's",
     'score_w': 63, 'score_l': 50, 'notes': 'UPSET. Texas A&M eliminates Saint Marys.'},
    {'region': 'South', 'seed_w': 2,  'winner': 'Houston',       'seed_l': 15, 'loser': 'Idaho',
     'score_w': 78, 'score_l': 47, 'notes': 'Houston dominant, 31-point win.'},
]

# Vegas spreads from mm_games (team_a was favored by this amount)
R1_SPREADS = {
    ('Duke', 'Siena'): -27.5,
    ('Ohio State', 'TCU'): -2.5,
    ("St. John's", 'Northern Iowa'): -9.5,
    ('Kansas', 'Cal Baptist'): -14.5,
    ('Louisville', 'USF'): -4.5,
    ('Michigan State', 'North Dakota State'): -16.5,
    ('UCLA', 'UCF'): -5.5,
    ('UConn', 'Furman'): -20.5,
    ('Arizona', 'LIU'): -30.5,
    ('Villanova', 'Utah State'): 1.5,   # Utah State was favored
    ('Wisconsin', 'High Point'): -10.5,
    ('Arkansas', 'Hawaii'): -15.5,
    ('BYU', 'Texas'): -2.5,
    ('Gonzaga', 'Kennesaw State'): -21.5,
    ('Miami FL', 'Missouri'): -1.5,
    ('Purdue', 'Queens'): -25.5,
    ('Michigan', 'Howard'): -30.5,
    ('Georgia', 'Saint Louis'): -2.5,   # Georgia was favored
    ('Texas Tech', 'Akron'): -7.5,
    ('Alabama', 'Hofstra'): -11.5,
    ('Tennessee', 'Miami OH'): -4.5,
    ('Virginia', 'Wright State'): -17.5,
    ('Kentucky', 'Santa Clara'): -3.5,
    ('Iowa State', 'Tennessee State'): -24.5,
    ('Florida', 'Prairie View A&M'): -35.5,
    ('Clemson', 'Iowa'): 2.5,   # Iowa was slightly favored (Clemson had positive spread)
    ('Vanderbilt', 'McNeese'): -11.5,
    ('Nebraska', 'Troy'): -12.5,
    ('UNC', 'VCU'): -2.5,
    ('Illinois', 'Penn'): -25.5,
    ("Saint Mary's", 'Texas A&M'): -3.5,
    ('Houston', 'Idaho'): -23.5,
}

# R2 matchups (based on bracket structure)
R2_MATCHUPS = [
    # EAST
    {'region': 'East', 'team_a': 'Duke',       'seed_a': 1,  'team_b': 'TCU',          'seed_b': 9},
    {'region': 'East', 'team_a': 'Kansas',      'seed_a': 4,  'team_b': "St. John's",   'seed_b': 5},
    {'region': 'East', 'team_a': 'Michigan State','seed_a': 3,'team_b': 'Louisville',   'seed_b': 6},
    {'region': 'East', 'team_a': 'UConn',       'seed_a': 2,  'team_b': 'UCLA',         'seed_b': 7},

    # WEST
    {'region': 'West', 'team_a': 'Arizona',     'seed_a': 1,  'team_b': 'Utah State',   'seed_b': 9},
    {'region': 'West', 'team_a': 'Arkansas',     'seed_a': 4,  'team_b': 'High Point',   'seed_b': 12},
    {'region': 'West', 'team_a': 'Gonzaga',      'seed_a': 3,  'team_b': 'Texas',        'seed_b': 11},
    {'region': 'West', 'team_a': 'Purdue',       'seed_a': 2,  'team_b': 'Miami FL',     'seed_b': 7},

    # MIDWEST
    {'region': 'Midwest', 'team_a': 'Michigan',    'seed_a': 1,  'team_b': 'Saint Louis', 'seed_b': 9},
    {'region': 'Midwest', 'team_a': 'Alabama',      'seed_a': 4,  'team_b': 'Texas Tech',  'seed_b': 5},
    {'region': 'Midwest', 'team_a': 'Virginia',     'seed_a': 3,  'team_b': 'Tennessee',   'seed_b': 6},
    {'region': 'Midwest', 'team_a': 'Iowa State',   'seed_a': 2,  'team_b': 'Kentucky',    'seed_b': 7},

    # SOUTH
    {'region': 'South', 'team_a': 'Florida',       'seed_a': 1,  'team_b': 'Iowa',        'seed_b': 9},
    {'region': 'South', 'team_a': 'Nebraska',       'seed_a': 4,  'team_b': 'Vanderbilt',  'seed_b': 5},
    {'region': 'South', 'team_a': 'Illinois',       'seed_a': 3,  'team_b': 'VCU',         'seed_b': 11},
    {'region': 'South', 'team_a': 'Houston',        'seed_a': 2,  'team_b': 'Texas A&M',   'seed_b': 10},
]


# ═══════════════════════════════════════════════
# STEP 1: COMPUTE R1 PERFORMANCE SIGNALS
# ═══════════════════════════════════════════════

def compute_r1_performance_signals(r1_results, r1_spreads):
    """Compute performance metrics from R1 actual results for each surviving team."""
    print("\n" + "=" * 60)
    print("COMPUTING R1 PERFORMANCE SIGNALS")
    print("=" * 60)

    signals = {}

    for game in r1_results:
        winner = game['winner']
        loser = game['loser']
        score_w = game['score_w']
        score_l = game['score_l']
        seed_w = game['seed_w']
        seed_l = game['seed_l']
        actual_margin = score_w - score_l

        # Find the spread — spread is from perspective of team_a in the original game
        expected_margin = None
        is_upset = seed_w > seed_l  # winner was higher seed = upset

        for (ta, tb), spread in r1_spreads.items():
            if (ta == winner and tb == loser):
                # Winner was team_a, spread was from their perspective
                expected_margin = abs(spread)  # how much team_a was expected to win by
                break
            elif (ta == loser and tb == winner):
                # Winner was team_b
                expected_margin = abs(spread)  # how much team_a was expected to win by
                # But team_a lost, so from winner's perspective, expected margin flips
                if spread < 0:
                    # team_a was favored (negative spread), team_b won = upset
                    expected_margin = -spread  # e.g., spread=-2.5 means team_a favored by 2.5
                    # Winner (team_b) was expected to LOSE by this much
                    expected_margin = -expected_margin  # winner was expected to be -2.5
                else:
                    # team_a was underdog (positive spread), team_b was favored
                    expected_margin = spread
                break

        # Simplified: compute expected_margin from winner's perspective
        # Find the game in spreads
        spread_val = None
        for (ta, tb), sp in r1_spreads.items():
            if ta == winner or ta == loser:
                if tb == winner or tb == loser:
                    spread_val = sp
                    # sp is from ta's perspective (negative = ta favored)
                    # Convert to winner's perspective
                    if ta == winner:
                        expected_margin_winner = -sp  # if sp=-27.5, winner expected +27.5
                    else:
                        expected_margin_winner = sp   # if sp=-2.5, loser was favored, winner expected -2.5 (underdog)
                    break

        if spread_val is None:
            expected_margin_winner = (seed_l - seed_w) * 2  # rough estimate
            print(f"  WARNING: No spread found for {winner} vs {loser}")

        margin_vs_spread = actual_margin - expected_margin_winner
        scare_factor = expected_margin_winner - actual_margin  # positive = team struggled
        dominance_score = actual_margin / max(abs(expected_margin_winner), 1)

        # Flags
        is_blowout = actual_margin >= 15
        is_close = actual_margin <= 5
        is_upset_winner = seed_w > seed_l

        signals[winner] = {
            'r1_score': score_w,
            'r1_opp_score': score_l,
            'r1_margin': actual_margin,
            'r1_expected_margin': round(expected_margin_winner, 1),
            'r1_margin_vs_spread': round(margin_vs_spread, 1),
            'r1_scare_factor': round(scare_factor, 1),
            'r1_dominance_score': round(dominance_score, 2),
            'r1_is_upset_winner': is_upset_winner,
            'r1_is_blowout': is_blowout,
            'r1_is_close_game': is_close,
            'r1_seed': seed_w,
            'r1_opp_seed': seed_l,
            'r1_notes': game['notes'],
        }

    # Print signals summary
    print(f"\n  {'Team':20s} {'Margin':>6s} {'Expected':>8s} {'vs Spread':>9s} {'Scare':>6s} {'Dom':>5s} {'Flags'}")
    print(f"  {'-'*75}")

    # Sort by scare factor (most concerning first)
    for team, s in sorted(signals.items(), key=lambda x: -x[1]['r1_scare_factor']):
        flags = []
        if s['r1_is_upset_winner']: flags.append('UPSET')
        if s['r1_is_blowout']: flags.append('BLOWOUT')
        if s['r1_is_close_game']: flags.append('CLOSE')
        if s['r1_scare_factor'] > 10: flags.append('RED FLAG')
        elif s['r1_scare_factor'] < -10: flags.append('GREEN FLAG')
        flag_str = ', '.join(flags) if flags else ''
        print(f"  ({s['r1_seed']:>2}) {team:18s} {s['r1_margin']:+5d} {s['r1_expected_margin']:+8.1f} "
              f"{s['r1_margin_vs_spread']:+9.1f} {s['r1_scare_factor']:+6.1f} {s['r1_dominance_score']:5.2f} {flag_str}")

    return signals


# ═══════════════════════════════════════════════
# STEP 2: EVALUATE V6 MODEL ACCURACY ON R1
# ═══════════════════════════════════════════════

def evaluate_r1_accuracy(r1_results, sb):
    """Check how V6 predictions performed on R1."""
    print("\n" + "=" * 60)
    print("R1 MODEL ACCURACY REPORT")
    print("=" * 60)

    # Fetch V6 predictions
    preds = sb.table('mm_ml_predictions').select('*').eq('round', 'R64').execute()
    pred_lookup = {}
    for p in preds.data:
        key = (p['team_a'], p['team_b'])
        pred_lookup[key] = p
        pred_lookup[(p['team_b'], p['team_a'])] = p

    # Build actual winner lookup
    actual_winners = {r['winner']: r for r in r1_results}
    actual_losers = {r['loser']: r for r in r1_results}

    # Track per-model accuracy
    model_correct = {'ensemble': 0, 'lr': 0, 'xgb': 0, 'agent': 0, 'vegas': 0}
    model_brier = {'ensemble': [], 'lr': [], 'xgb': [], 'agent': []}
    total = 0
    upsets_predicted = 0
    upsets_actual = 0
    upsets_correctly_predicted = 0

    print(f"\n  {'Game':45s} {'Pick':18s} {'Actual':18s} {'Correct':>7s} {'Ens%':>6s}")
    print(f"  {'-'*100}")

    for game in r1_results:
        winner = game['winner']
        loser = game['loser']
        seed_w = game['seed_w']
        seed_l = game['seed_l']
        is_upset = seed_w > seed_l

        if is_upset:
            upsets_actual += 1

        # Find prediction
        pred = pred_lookup.get((winner, loser)) or pred_lookup.get((loser, winner))
        if not pred:
            print(f"  WARNING: No prediction found for {winner} vs {loser}")
            continue

        total += 1
        pick = pred['pick']
        correct = pick == winner

        # Determine prob of actual winner
        if pred['team_a'] == winner:
            prob_winner = pred['ensemble_prob_a']
            lr_prob_w = pred['lr_prob_a']
            xgb_prob_w = pred['xgb_prob_a']
            agent_prob_w = pred['agent_prob_a']
        else:
            prob_winner = pred['ensemble_prob_b']
            lr_prob_w = 1 - pred['lr_prob_a']
            xgb_prob_w = 1 - pred['xgb_prob_a']
            agent_prob_w = 1 - pred['agent_prob_a']

        if correct:
            model_correct['ensemble'] += 1
        if (pred['team_a'] == winner and lr_prob_w >= 0.5) or (pred['team_b'] == winner and lr_prob_w >= 0.5):
            model_correct['lr'] += 1
        if (pred['team_a'] == winner and xgb_prob_w >= 0.5) or (pred['team_b'] == winner and xgb_prob_w >= 0.5):
            model_correct['xgb'] += 1
        if (pred['team_a'] == winner and agent_prob_w >= 0.5) or (pred['team_b'] == winner and agent_prob_w >= 0.5):
            model_correct['agent'] += 1

        # Vegas: check if the favorite won
        # Simplified: if vegas_prob_a > 0.5 and team_a won, or vice versa
        vegas_correct = False
        # We need to determine vegas pick from the spread
        for (ta, tb), sp in R1_SPREADS.items():
            if (ta == winner or ta == loser) and (tb == winner or tb == loser):
                # sp negative = ta favored
                vegas_pick = ta if sp < 0 else tb
                if vegas_pick == winner:
                    model_correct['vegas'] += 1
                    vegas_correct = True
                break

        # Upset tracking
        if is_upset:
            # Did we pick the underdog?
            underdog = winner  # the upset winner IS the underdog
            if pick == underdog:
                upsets_correctly_predicted += 1
            # Did model flag this as a potential upset?
            if pred['pick'] != winner:
                # We didn't pick the upset, but did we flag it?
                pass  # upset_probability was None for V6 R64

        # Brier scores
        model_brier['ensemble'].append((1 - prob_winner) ** 2)
        model_brier['lr'].append((1 - lr_prob_w) ** 2)
        model_brier['xgb'].append((1 - xgb_prob_w) ** 2)
        model_brier['agent'].append((1 - agent_prob_w) ** 2)

        marker = "✓" if correct else "✗"
        upset_tag = " UPSET" if is_upset else ""
        game_str = f"({seed_w}){winner} over ({seed_l}){loser}{upset_tag}"
        print(f"  {game_str:45s} {pick:18s} {winner:18s} {marker:>7s} {prob_winner:6.1%}")

    print(f"\n  {'─'*60}")
    print(f"  MODEL ACCURACY SUMMARY (R1 — {total} games)")
    print(f"  {'─'*60}")
    print(f"  {'Model':15s} {'Correct':>8s} {'Accuracy':>10s} {'Brier':>8s}")
    print(f"  {'─'*45}")
    for model in ['ensemble', 'lr', 'xgb', 'agent', 'vegas']:
        acc = model_correct[model] / total if total > 0 else 0
        brier = np.mean(model_brier.get(model, [0])) if model in model_brier else 'N/A'
        brier_str = f"{brier:.4f}" if isinstance(brier, float) else brier
        print(f"  {model:15s} {model_correct[model]:>5d}/{total:<2d} {acc:10.1%} {brier_str:>8s}")

    print(f"\n  UPSET ANALYSIS:")
    print(f"    Actual upsets in R1: {upsets_actual}")
    print(f"    Upsets correctly predicted: {upsets_correctly_predicted}/{upsets_actual}")

    # Identify which models to weight more
    print(f"\n  WEIGHT ADJUSTMENT RECOMMENDATIONS:")
    best_model = max(model_correct, key=model_correct.get)
    worst_model = min(model_correct, key=model_correct.get)
    print(f"    Best performer: {best_model} ({model_correct[best_model]}/{total})")
    print(f"    Worst performer: {worst_model} ({model_correct[worst_model]}/{total})")

    return model_correct, total, upsets_actual, upsets_correctly_predicted


# ═══════════════════════════════════════════════
# STEP 3: UPDATE SUPABASE WITH R1 RESULTS
# ═══════════════════════════════════════════════

def update_supabase_r1_results(sb, r1_results):
    """Update mm_teams and mm_games with actual R1 results."""
    print("\n" + "=" * 60)
    print("UPDATING SUPABASE WITH R1 RESULTS")
    print("=" * 60)

    # 1. Update mm_teams — set eliminated teams
    losers = [r['loser'] for r in r1_results]
    winners = [r['winner'] for r in r1_results]

    teams_resp = sb.table('mm_teams').select('id,name,tournament_wins').execute()
    team_id_lookup = {t['name']: t['id'] for t in teams_resp.data}

    updated = 0
    for loser in losers:
        tid = team_id_lookup.get(loser)
        if tid:
            sb.table('mm_teams').update({
                'eliminated': True,
                'eliminated_round': 'R64',
            }).eq('id', tid).execute()
            updated += 1
    print(f"  Marked {updated} teams as eliminated in R64")

    # Set tournament_wins=1 for winners
    for winner in winners:
        tid = team_id_lookup.get(winner)
        if tid:
            sb.table('mm_teams').update({
                'tournament_wins': 1,
            }).eq('id', tid).execute()
    print(f"  Updated {len(winners)} winners with tournament_wins=1")

    # 2. Update mm_games R64 — set actual_winner and status
    r64_games = sb.table('mm_games').select('id,team_a,team_b,round').eq('round', 'R64').execute()

    # Build winner lookup
    winner_lookup = {}
    for r in r1_results:
        winner_lookup[(r['winner'], r['loser'])] = r['winner']
        winner_lookup[(r['loser'], r['winner'])] = r['winner']

    games_updated = 0
    for g in r64_games.data:
        key = (g['team_a'], g['team_b'])
        actual_winner = winner_lookup.get(key)
        if actual_winner:
            sb.table('mm_games').update({
                'actual_winner': actual_winner,
                'status': 'final',
            }).eq('id', g['id']).execute()
            games_updated += 1
    print(f"  Updated {games_updated} R64 games with actual winners")

    # 3. Fix R32 matchups — update existing ones with correct teams
    r32_existing = sb.table('mm_games').select('id,team_a,team_b,region').eq('round', 'R32').execute()
    existing_by_region = {}
    for g in r32_existing.data:
        r = g['region']
        if r not in existing_by_region:
            existing_by_region[r] = []
        existing_by_region[r].append(g)

    # Update existing R32 games with correct matchups, or insert new ones
    r32_updated = 0
    r32_inserted = 0
    for m in R2_MATCHUPS:
        region_games = existing_by_region.get(m['region'], [])
        if region_games:
            # Reuse an existing game row
            g = region_games.pop(0)
            sb.table('mm_games').update({
                'team_a': m['team_a'],
                'team_b': m['team_b'],
                'status': 'pending',
                'actual_winner': '',
            }).eq('id', g['id']).execute()
            r32_updated += 1
        else:
            # Insert new game
            sb.table('mm_games').insert({
                'team_a': m['team_a'],
                'team_b': m['team_b'],
                'round': 'R32',
                'region': m['region'],
                'status': 'pending',
            }).execute()
            r32_inserted += 1
    print(f"  Updated {r32_updated} R32 games, inserted {r32_inserted} new R32 games")


# ═══════════════════════════════════════════════
# STEP 4: BUILD R2 FEATURES WITH R1 SIGNALS
# ═══════════════════════════════════════════════

def build_r2_features(tables, r1_signals, team_lookup):
    """Build enhanced features for R2 matchups including R1 performance signals."""
    print("\n" + "=" * 60)
    print("BUILDING R2 FEATURES (with R1 performance signals)")
    print("=" * 60)

    matchup_features = []

    for m in R2_MATCHUPS:
        team_a = m['team_a']
        team_b = m['team_b']
        region = m['region']

        ta = team_lookup.get(team_a)
        tb = team_lookup.get(team_b)
        if ta is None or tb is None:
            print(f"  WARNING: Missing team data for {team_a} or {team_b}")
            continue

        # Base V5 delta features
        features = compute_delta_features(ta, tb, round_num=2)

        # R1 performance signal features
        sig_a = r1_signals.get(team_a, {})
        sig_b = r1_signals.get(team_b, {})

        features['r1_margin_vs_spread_a'] = sig_a.get('r1_margin_vs_spread', 0)
        features['r1_margin_vs_spread_b'] = sig_b.get('r1_margin_vs_spread', 0)
        features['r1_scare_factor_a'] = sig_a.get('r1_scare_factor', 0)
        features['r1_scare_factor_b'] = sig_b.get('r1_scare_factor', 0)
        features['r1_dominance_score_a'] = sig_a.get('r1_dominance_score', 1.0)
        features['r1_dominance_score_b'] = sig_b.get('r1_dominance_score', 1.0)

        features['r1_margin_vs_spread_delta'] = features['r1_margin_vs_spread_a'] - features['r1_margin_vs_spread_b']
        features['r1_dominance_delta'] = features['r1_dominance_score_a'] - features['r1_dominance_score_b']

        features['r1_upset_winner_a'] = 1 if sig_a.get('r1_is_upset_winner', False) else 0
        features['r1_upset_winner_b'] = 1 if sig_b.get('r1_is_upset_winner', False) else 0
        features['r1_blowout_winner_a'] = 1 if sig_a.get('r1_is_blowout', False) else 0
        features['r1_blowout_winner_b'] = 1 if sig_b.get('r1_is_blowout', False) else 0
        features['r1_close_game_survivor_a'] = 1 if sig_a.get('r1_is_close_game', False) else 0
        features['r1_close_game_survivor_b'] = 1 if sig_b.get('r1_is_close_game', False) else 0

        # Agent swarm features (fetch from R32 games if available, else use R64 data)
        games_df = tables['mm_games']
        game_row = games_df[(games_df['team_a'] == team_a) & (games_df['team_b'] == team_b) & (games_df['round'] == 'R32')]
        if game_row.empty:
            game_row = games_df[(games_df['team_b'] == team_a) & (games_df['team_a'] == team_b) & (games_df['round'] == 'R32')]

        if not game_row.empty:
            g = game_row.iloc[0]
            vote_a = float(g.get('vote_count_a', 0) or 0)
            vote_b = float(g.get('vote_count_b', 0) or 0)
            total_votes = vote_a + vote_b
            features['agent_consensus_a'] = vote_a / total_votes if total_votes > 0 else 0.5
            features['agent_win_prob_a'] = float(g.get('team_a_win_prob', 0.5) or 0.5)
            features['agent_uncertainty'] = float(g.get('combined_uncertainty', 0.3) or 0.3)
        else:
            features['agent_consensus_a'] = 0.5
            features['agent_win_prob_a'] = 0.5
            features['agent_uncertainty'] = 0.3

        # No Vegas lines for R2 yet — will use model-generated
        features['vegas_prob_a'] = np.nan
        features['_has_vegas'] = False

        # MC features
        mc_df = tables['mm_monte_carlo']
        mc_a_row = mc_df[mc_df['team_name'] == team_a]
        mc_b_row = mc_df[mc_df['team_name'] == team_b]
        mc_a = mc_a_row.iloc[0].to_dict() if not mc_a_row.empty else {}
        mc_b = mc_b_row.iloc[0].to_dict() if not mc_b_row.empty else {}
        features['mc_s16_prob_delta'] = float(mc_a.get('prob_s16', 0) or 0) - float(mc_b.get('prob_s16', 0) or 0)
        features['mc_e8_prob_delta'] = float(mc_a.get('prob_e8', 0) or 0) - float(mc_b.get('prob_e8', 0) or 0)
        features['mc_winner_prob_delta'] = float(mc_a.get('prob_winner', 0) or 0) - float(mc_b.get('prob_winner', 0) or 0)

        # Metadata
        features['_team_a'] = team_a
        features['_team_b'] = team_b
        features['_round'] = 'R32'
        features['_region'] = region
        features['_seed_a'] = m['seed_a']
        features['_seed_b'] = m['seed_b']

        matchup_features.append(features)

    matchups_df = pd.DataFrame(matchup_features)
    print(f"  Built features for {len(matchups_df)} R2 matchups")
    return matchups_df


# ═══════════════════════════════════════════════
# STEP 5: R2-SPECIFIC ADJUSTMENTS
# ═══════════════════════════════════════════════

def apply_r2_adjustments(results_df, r1_signals):
    """Apply R2-specific adjustments based on R1 performance."""
    print("\n" + "=" * 60)
    print("APPLYING R2-SPECIFIC ADJUSTMENTS")
    print("=" * 60)

    adjusted = results_df['ensemble_prob_a'].values.copy()

    for idx, row in results_df.iterrows():
        i = results_df.index.get_loc(idx)
        team_a = row['_team_a']
        team_b = row['_team_b']
        sig_a = r1_signals.get(team_a, {})
        sig_b = r1_signals.get(team_b, {})

        adj_total = 0.0
        reasons = []

        # 1. "Battle-tested" bonus: teams that won close R1 games
        if sig_a.get('r1_is_close_game', False):
            adj_total += 0.01
            reasons.append(f"+1% battle-tested ({team_a})")
        if sig_b.get('r1_is_close_game', False):
            adj_total -= 0.01
            reasons.append(f"+1% battle-tested ({team_b})")

        # 2. "Scare hangover" penalty: teams that massively underperformed
        sf_a = sig_a.get('r1_scare_factor', 0)
        sf_b = sig_b.get('r1_scare_factor', 0)
        if sf_a > 15:
            adj_total -= 0.02
            reasons.append(f"-2% scare hangover ({team_a}, SF={sf_a:+.1f})")
        elif sf_a > 8:
            adj_total -= 0.01
            reasons.append(f"-1% scare hangover ({team_a}, SF={sf_a:+.1f})")
        if sf_b > 15:
            adj_total += 0.02
            reasons.append(f"-2% scare hangover ({team_b}, SF={sf_b:+.1f})")
        elif sf_b > 8:
            adj_total += 0.01
            reasons.append(f"-1% scare hangover ({team_b}, SF={sf_b:+.1f})")

        # 3. "Momentum steamroller" bonus: teams that dominated R1
        dom_a = sig_a.get('r1_dominance_score', 1.0)
        dom_b = sig_b.get('r1_dominance_score', 1.0)
        margin_a = sig_a.get('r1_margin', 0)
        margin_b = sig_b.get('r1_margin', 0)
        if margin_a >= 25 and dom_a > 1.0:
            adj_total += 0.02
            reasons.append(f"+2% steamroller ({team_a}, margin={margin_a})")
        elif margin_a >= 15 and dom_a > 1.0:
            adj_total += 0.01
            reasons.append(f"+1% steamroller ({team_a}, margin={margin_a})")
        if margin_b >= 25 and dom_b > 1.0:
            adj_total -= 0.02
            reasons.append(f"+2% steamroller ({team_b}, margin={margin_b})")
        elif margin_b >= 15 and dom_b > 1.0:
            adj_total -= 0.01
            reasons.append(f"+1% steamroller ({team_b}, margin={margin_b})")

        # 4. "Cinderella confidence" bonus: upset winners playing with house money
        if sig_a.get('r1_is_upset_winner', False):
            adj_total += 0.01
            reasons.append(f"+1% Cinderella ({team_a})")
        if sig_b.get('r1_is_upset_winner', False):
            adj_total -= 0.01
            reasons.append(f"+1% Cinderella ({team_b})")

        if abs(adj_total) > 0.001:
            adjusted[i] += adj_total
            print(f"  {team_a} vs {team_b}: net adj = {adj_total:+.1%}")
            for r in reasons:
                print(f"    {r}")

    results_df['ensemble_prob_a'] = np.clip(adjusted, 0.02, 0.98)
    results_df['ensemble_prob_b'] = 1 - results_df['ensemble_prob_a']
    results_df['pick'] = results_df.apply(
        lambda r: r['_team_a'] if r['ensemble_prob_a'] >= 0.5 else r['_team_b'], axis=1)
    results_df['pick_confidence'] = np.maximum(results_df['ensemble_prob_a'], results_df['ensemble_prob_b'])

    def get_tier(p):
        m = max(p, 1-p)
        if m > 0.75: return 'LOCK'
        elif m > 0.65: return 'STRONG'
        elif m > 0.55: return 'LEAN'
        else: return 'TOSS-UP'

    results_df['confidence_tier'] = results_df['pick_confidence'].apply(get_tier)
    return results_df


# ═══════════════════════════════════════════════
# STEP 6: R2 SIMULATION WITH R1 SIGNALS
# ═══════════════════════════════════════════════

def simulate_r2_bracket(results_df, team_lookup, r1_signals, n_sims=N_SIMULATIONS):
    """Run variance-aware simulation for R2 onward."""
    print("\n" + "=" * 60)
    print(f"R2 BRACKET SIMULATION ({n_sims:,} sims)")
    print("=" * 60)

    # Build probability lookup from R2 predictions
    prob_lookup = {}
    for _, row in results_df.iterrows():
        prob_lookup[(row['_team_a'], row['_team_b'])] = row['ensemble_prob_a']
        prob_lookup[(row['_team_b'], row['_team_a'])] = row['ensemble_prob_b']

    def base_gwp(ta, tb):
        if (ta, tb) in prob_lookup: return prob_lookup[(ta, tb)]
        a, b = team_lookup.get(ta, {}), team_lookup.get(tb, {})
        return expit(0.035 * (a.get('adj_efficiency_margin', 0) - b.get('adj_efficiency_margin', 0)))

    # Build regions from R2 matchups
    regions = {}
    for m in R2_MATCHUPS:
        r = m['region']
        if r not in regions:
            regions[r] = []
        regions[r].append(m)

    # R2 pairs by region (4 games per region)
    all_teams = set()
    for m in R2_MATCHUPS:
        all_teams.add(m['team_a'])
        all_teams.add(m['team_b'])

    adv = {t: {'S16': 0, 'E8': 0, 'F4': 0, 'Champ': 0, 'Win': 0} for t in all_teams}
    rng = np.random.RandomState(2026)

    for sim in range(n_sims):
        # Draw tournament performance modifier
        team_mods = {}
        for team in all_teams:
            td = team_lookup.get(team, {})
            base_var = 0.018
            sig = r1_signals.get(team, {})

            # R1 performance adjusts variance: teams that dominated are more stable
            dom = sig.get('r1_dominance_score', 1.0)
            if dom > 1.5:
                base_var *= 0.85  # more predictable if they crushed R1
            elif dom < 0.5:
                base_var *= 1.15  # more volatile if they struggled

            three_pt_vol = (td.get('three_pt_pct', 0.34) - 0.34) / 0.10
            youth = (8.0 - td.get('experience_score', 5.5)) / 8.0
            pv = (td.get('performance_variance', 12.0) - 10.0) / 10.0
            conf = td.get('conference', '')
            conf_jump = 0.15 if conf not in POWER_CONFERENCES else 0.0
            def_stab = max(0, (92.0 - td.get('adj_d', 95)) / 15.0)

            var_width = base_var * (
                1.0 + 0.20 * three_pt_vol + 0.20 * youth + 0.15 * pv
                + conf_jump - 0.20 * def_stab
            )
            var_width = max(0.025, min(0.09, var_width))
            team_mods[team] = rng.normal(0, var_width)

        def gwp_var(ta, tb):
            bp = base_gwp(ta, tb)
            mod = team_mods.get(ta, 0) - team_mods.get(tb, 0)
            return np.clip(bp + mod, 0.05, 0.95)

        # Simulate R2 -> Championship
        region_winners = {}
        for region, matchups in regions.items():
            # R32 (4 games)
            r32_winners = []
            for m in matchups:
                ta, tb = m['team_a'], m['team_b']
                w = ta if rng.random() < gwp_var(ta, tb) else tb
                r32_winners.append(w)
                adv[w]['S16'] += 1

            # S16 (2 games)
            s16_winners = []
            for i in range(0, 4, 2):
                ta, tb = r32_winners[i], r32_winners[i+1]
                w = ta if rng.random() < gwp_var(ta, tb) else tb
                s16_winners.append(w)
                adv[w]['E8'] += 1

            # E8 (1 game)
            ta, tb = s16_winners[0], s16_winners[1]
            rw = ta if rng.random() < gwp_var(ta, tb) else tb
            adv[rw]['F4'] += 1
            region_winners[region] = rw

        # F4
        rw_list = list(region_winners.values())
        if len(rw_list) >= 4:
            f1 = rw_list[0] if rng.random() < gwp_var(rw_list[0], rw_list[1]) else rw_list[1]
            f2 = rw_list[2] if rng.random() < gwp_var(rw_list[2], rw_list[3]) else rw_list[3]
            adv[f1]['Champ'] += 1
            adv[f2]['Champ'] += 1
            ch = f1 if rng.random() < gwp_var(f1, f2) else f2
            adv[ch]['Win'] += 1

    # Build simulation results
    sim_results = []
    for team, counts in adv.items():
        td = team_lookup.get(team, {})
        seed = td.get('seed', 16)
        sig = r1_signals.get(team, {})
        sim_results.append({
            'team': team, 'seed': seed,
            'region': next((m['region'] for m in R2_MATCHUPS if m['team_a'] == team or m['team_b'] == team), ''),
            'prob_s16': round(min(counts['S16'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_e8': round(min(counts['E8'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_f4': round(min(counts['F4'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_championship': round(min(counts['Champ'] / n_sims, CEILING_CHAMP.get(seed, 1.0)), 4),
            'prob_winner': round(min(counts['Win'] / n_sims, CEILING_WINNER.get(seed, 1.0)), 4),
        })
    sim_df = pd.DataFrame(sim_results).sort_values('prob_winner', ascending=False)

    print("\n  TOP 20 CHAMPIONSHIP CONTENDERS (Post-R1, Variance-Aware):")
    print(f"  {'Team':25s} {'Seed':>4s} {'S16':>7s} {'E8':>7s} {'F4':>7s} {'Champ':>7s} {'Win':>7s}")
    print(f"  {'-'*70}")
    for _, t in sim_df.head(20).iterrows():
        print(f"  {t['team']:25s} {t['seed']:4d} {t['prob_s16']:7.1%} {t['prob_e8']:7.1%} "
              f"{t['prob_f4']:7.1%} {t['prob_championship']:7.1%} {t['prob_winner']:7.1%}")

    return sim_df


# ═══════════════════════════════════════════════
# STEP 7: WRITE R2 RESULTS TO SUPABASE
# ═══════════════════════════════════════════════

def write_r2_to_supabase(sb, results_df, sim_df):
    """Write R2 predictions and updated simulations to Supabase."""
    print("\n" + "=" * 60)
    print("WRITING R2 RESULTS TO SUPABASE")
    print("=" * 60)

    def safe_float(v):
        f = float(v)
        return 0.5 if np.isnan(f) else f

    # Insert R2 predictions (don't delete R64 — keep them for history)
    # Delete old R32 predictions
    try:
        sb.table('mm_ml_predictions').delete().eq('round', 'R32').execute()
    except:
        pass

    pred = []
    for _, r in results_df.iterrows():
        pred.append({
            'team_a': r['_team_a'], 'team_b': r['_team_b'],
            'round': r['_round'], 'region': r['_region'],
            'seed_a': int(r['_seed_a']), 'seed_b': int(r['_seed_b']),
            'lr_prob_a': safe_float(r['lr_prob_a']),
            'xgb_prob_a': safe_float(r['xgb_prob_a']),
            'agent_prob_a': safe_float(r.get('agent_prob_a', 0.5)),
            'mc_prob_a': safe_float(r.get('mc_prob_a', 0.5)),
            'ensemble_prob_a': safe_float(r['ensemble_prob_a']),
            'ensemble_prob_b': safe_float(r['ensemble_prob_b']),
            'pick': r['pick'],
            'pick_confidence': safe_float(r['pick_confidence']),
            'confidence_tier': r['confidence_tier'],
            'upset_probability': safe_float(r.get('upset_probability', 0)),
        })
    sb.table('mm_ml_predictions').insert(pred).execute()
    print(f"  Inserted {len(pred)} R2 predictions")

    # Update simulations (replace all)
    try:
        sb.table('mm_ml_simulations').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
    except:
        pass

    sims = []
    for _, r in sim_df.iterrows():
        sims.append({
            'team': r['team'], 'seed': int(r['seed']), 'region': r['region'],
            'prob_s16': float(r['prob_s16']), 'prob_e8': float(r['prob_e8']),
            'prob_f4': float(r['prob_f4']), 'prob_championship': float(r['prob_championship']),
            'prob_winner': float(r['prob_winner']), 'n_simulations': N_SIMULATIONS,
        })
    for i in range(0, len(sims), 50):
        sb.table('mm_ml_simulations').insert(sims[i:i+50]).execute()
    print(f"  Inserted {len(sims)} simulation records")


# ═══════════════════════════════════════════════
# HISTORICAL MATCHUP SIMILARITY (KNN)
# ═══════════════════════════════════════════════

def historical_similarity_model(hist_df, r2_matchups_df, scaler, k=25):
    """Find historically similar matchups and use their outcomes as a signal.

    For each R2 game, finds the k most similar games from real historical data
    (2008-2025, 1072 games) based on euclidean distance on normalized features.
    Returns the win rate of team_a in those similar matchups.
    """
    from sklearn.metrics.pairwise import euclidean_distances

    print("\n" + "=" * 60)
    print(f"HISTORICAL SIMILARITY MODEL (k={k} nearest neighbors)")
    print("=" * 60)

    # Use all shared features for similarity comparison
    X_hist = hist_df[SHARED_FEATURES].values
    y_hist = hist_df['outcome'].values
    X_hist_scaled = scaler.transform(X_hist)

    # Get R2 features
    X_r2 = r2_matchups_df[SHARED_FEATURES].values
    X_r2_scaled = scaler.transform(X_r2)

    # Compute distances from each R2 game to all historical games
    distances = euclidean_distances(X_r2_scaled, X_hist_scaled)

    knn_probs = []
    knn_details = []

    print(f"\n  {'Game':45s} {'KNN prob':>8s} {'k':>3s} {'R32 only':>8s} {'Seed match':>10s}")
    print(f"  {'-'*80}")

    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"

        # Find k nearest neighbors
        nn_indices = np.argsort(distances[i])[:k]
        nn_outcomes = y_hist[nn_indices]
        nn_distances = distances[i][nn_indices]

        # Distance-weighted win rate (closer matches count more)
        weights = 1.0 / (nn_distances + 0.01)  # add small epsilon to avoid div by 0
        weighted_prob = np.average(nn_outcomes, weights=weights)

        # Also compute: among just R32 historical games (round_num==2)
        r32_mask = hist_df['round_num'].values == 2
        r32_indices = np.where(r32_mask)[0]
        if len(r32_indices) > 0:
            r32_distances = distances[i][r32_indices]
            r32_nn = r32_indices[np.argsort(r32_distances)[:min(k, len(r32_indices))]]
            r32_outcomes = y_hist[r32_nn]
            r32_dists = distances[i][r32_nn]
            r32_weights = 1.0 / (r32_dists + 0.01)
            r32_prob = np.average(r32_outcomes, weights=r32_weights)
        else:
            r32_prob = weighted_prob

        # Also: among games with same seed matchup (e.g., 4 vs 5)
        sa, sb_ = int(row['_seed_a']), int(row['_seed_b'])
        seed_mask = (hist_df['seed_a_val'].values == sa) & (hist_df['seed_b_val'].values == sb_)
        seed_indices = np.where(seed_mask)[0]
        if len(seed_indices) >= 5:
            seed_outcomes = y_hist[seed_indices]
            seed_prob = seed_outcomes.mean()
            seed_n = len(seed_indices)
        else:
            seed_prob = weighted_prob
            seed_n = 0

        # Blend: 50% all-game KNN, 30% R32-only KNN, 20% seed-match rate
        blended_prob = 0.50 * weighted_prob + 0.30 * r32_prob + 0.20 * seed_prob
        blended_prob = np.clip(blended_prob, 0.05, 0.95)

        knn_probs.append(blended_prob)

        # Show the 3 closest matches for context
        top3_games = []
        for j in nn_indices[:3]:
            h = hist_df.iloc[j]
            outcome_str = "team_a" if h['outcome'] == 1 else "team_b"
            dist = distances[i][j]
            top3_games.append(f"d={dist:.2f} -> {outcome_str}")

        detail = {
            'game': game,
            'knn_prob': round(weighted_prob, 3),
            'r32_prob': round(r32_prob, 3),
            'seed_prob': round(seed_prob, 3),
            'blended_prob': round(blended_prob, 3),
            'seed_n': seed_n,
            'top3': top3_games,
        }
        knn_details.append(detail)

        print(f"  {game:45s} {blended_prob:8.1%} {k:3d} {r32_prob:8.1%} {seed_prob:8.1%} (n={seed_n})")

    # Show how KNN compares to other models
    print(f"\n  KNN DIVERGENCE FROM LR (where KNN disagrees most):")
    print(f"  {'Game':45s} {'KNN':>6s} {'LR':>6s} {'Gap':>6s}")
    print(f"  {'-'*65}")
    # We don't have LR probs yet, so just print KNN for now
    for d in sorted(knn_details, key=lambda x: abs(x['blended_prob'] - 0.5)):
        print(f"  {d['game']:45s} {d['blended_prob']:6.1%}")

    return knn_probs, knn_details


# ═══════════════════════════════════════════════
# ENHANCEMENT 1: BAYESIAN UPDATING FROM R1 RESULTS
# ═══════════════════════════════════════════════

def bayesian_update_team_lookup(team_lookup, r1_results, r1_spreads):
    """Update team AEM values using Bayesian posterior from R1 actual performance."""
    print("\n" + "=" * 60)
    print("BAYESIAN AEM UPDATE FROM R1 RESULTS")
    print("=" * 60)

    updated_count = 0
    print(f"\n  {'Team':20s} {'Prior AEM':>10s} {'R1 Margin':>10s} {'R1 Implied':>12s} {'Posterior':>10s} {'Shift':>8s}")
    print(f"  {'-'*75}")

    for game in r1_results:
        winner = game['winner']
        score_w = game['score_w']
        score_l = game['score_l']
        actual_margin = score_w - score_l

        if winner not in team_lookup:
            continue

        prior_aem = team_lookup[winner].get('adj_efficiency_margin', 0)

        # r1_implied_aem: single game is noisy, so blend with prior
        r1_implied_aem = actual_margin * 0.5 + prior_aem * 0.5

        # Bayesian posterior with shrinkage toward prior
        posterior_aem = prior_aem * 0.7 + r1_implied_aem * 0.3
        shift = posterior_aem - prior_aem

        print(f"  {winner:20s} {prior_aem:+10.2f} {actual_margin:+10d} {r1_implied_aem:+12.2f} {posterior_aem:+10.2f} {shift:+8.2f}")

        # Update team_lookup with posterior AEM
        team_lookup[winner]['adj_efficiency_margin'] = posterior_aem
        # Also update adj_o to be consistent (keep adj_d fixed, shift adj_o)
        team_lookup[winner]['adj_o'] = team_lookup[winner]['adj_d'] + posterior_aem
        updated_count += 1

    print(f"\n  Updated AEM for {updated_count} surviving teams")
    return team_lookup


# ═══════════════════════════════════════════════
# ENHANCEMENT 2: RECENCY WEIGHTING
# ═══════════════════════════════════════════════

def compute_recency_weights(hist_df):
    """Compute sample weights for historical data based on recency."""
    print("\n" + "=" * 60)
    print("RECENCY WEIGHTING FOR TRAINING DATA")
    print("=" * 60)

    weights = np.ones(len(hist_df))
    years = hist_df['year'].values

    mask_recent = (years >= 2022) & (years <= 2025)
    mask_mid = (years >= 2018) & (years <= 2021)
    mask_old = years < 2018

    weights[mask_recent] = 3.0
    weights[mask_mid] = 2.0
    weights[mask_old] = 1.0

    print(f"  2022-2025 (weight=3.0): {mask_recent.sum()} games")
    print(f"  2018-2021 (weight=2.0): {mask_mid.sum()} games")
    print(f"  2008-2017 (weight=1.0): {mask_old.sum()} games")
    print(f"  Effective sample size: {weights.sum():.0f} (from {len(hist_df)} actual games)")

    return weights


# ═══════════════════════════════════════════════
# ENHANCEMENT 3: SHAP VALUES PER GAME
# ═══════════════════════════════════════════════

def compute_shap_values(xgb_base_v2, X_r2_clean, r2_matchups_df, clean_features):
    """Compute SHAP values for XGB v2 on each R2 matchup."""
    print("\n" + "=" * 60)
    print("SHAP VALUES — TOP DRIVING FEATURES PER R2 GAME")
    print("=" * 60)

    try:
        import shap
        explainer = shap.TreeExplainer(xgb_base_v2)
        shap_values = explainer.shap_values(X_r2_clean)

        for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
            game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
            sv = shap_values[i]
            top_idx = np.argsort(np.abs(sv))[::-1][:3]
            print(f"\n  {game}:")
            for j in top_idx:
                print(f"    {clean_features[j]:35s} value={X_r2_clean[i, j]:+.3f}  SHAP={sv[j]:+.4f}")

    except ImportError:
        print("  shap library not available — using feature_importance fallback")
        importances = xgb_base_v2.feature_importances_
        for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
            game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
            # Per-game contribution: feature_value * feature_importance
            contributions = X_r2_clean[i] * importances
            top_idx = np.argsort(np.abs(contributions))[::-1][:3]
            print(f"\n  {game}:")
            for j in top_idx:
                print(f"    {clean_features[j]:35s} value={X_r2_clean[i, j]:+.3f}  contrib={contributions[j]:+.4f}  (imp={importances[j]:.4f})")


# ═══════════════════════════════════════════════
# ENHANCEMENT 4: BOOTSTRAP CONFIDENCE INTERVALS
# ═══════════════════════════════════════════════

def bootstrap_confidence_intervals(X_clean, y_hist, X_r2_clean, X_r2_clean_scaled_fn,
                                   r2_matchups_df, clean_features, n_boot=200):
    """Resample training data and retrain to get confidence intervals per game."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import xgboost as xgb

    print("\n" + "=" * 60)
    print(f"BOOTSTRAP CONFIDENCE INTERVALS ({n_boot} iterations)")
    print("=" * 60)

    n_games = X_r2_clean.shape[0]
    boot_preds_lr = np.zeros((n_boot, n_games))
    boot_preds_xgb = np.zeros((n_boot, n_games))

    rng = np.random.RandomState(42)
    n_samples = len(X_clean)

    for b in range(n_boot):
        # Resample with replacement
        idx = rng.choice(n_samples, size=n_samples, replace=True)
        X_b = X_clean[idx]
        y_b = y_hist[idx]

        # LR
        scaler_b = StandardScaler()
        X_b_scaled = scaler_b.fit_transform(X_b)
        lr_b = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
        lr_b.fit(X_b_scaled, y_b)
        X_r2_b_scaled = scaler_b.transform(X_r2_clean)
        boot_preds_lr[b] = lr_b.predict_proba(X_r2_b_scaled)[:, 1]

        # XGB
        xgb_b = xgb.XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.03,
            subsample=0.7, colsample_bytree=0.7,
            reg_alpha=1.0, reg_lambda=3.0,
            min_child_weight=10, gamma=0.5,
            random_state=42, eval_metric='logloss', use_label_encoder=False,
            verbosity=0,
        )
        xgb_b.fit(X_b, y_b)
        boot_preds_xgb[b] = xgb_b.predict_proba(X_r2_clean)[:, 1]

    # Average of LR and XGB bootstrap predictions
    boot_preds_avg = (boot_preds_lr + boot_preds_xgb) / 2.0

    print(f"\n  {'Game':45s} {'Mean':>6s} {'5th%':>6s} {'95th%':>6s} {'Width':>6s} {'Verdict'}")
    print(f"  {'-'*85}")

    ci_results = []
    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
        preds = boot_preds_avg[:, i]
        p5 = np.percentile(preds, 5)
        p95 = np.percentile(preds, 95)
        mean_p = np.mean(preds)
        width = p95 - p5

        if width > 0.20:
            verdict = "FRAGILE (wide CI)"
        elif width < 0.10:
            verdict = "ROBUST (narrow CI)"
        else:
            verdict = "MODERATE"

        ci_results.append({'game': game, 'mean': mean_p, 'p5': p5, 'p95': p95, 'width': width, 'verdict': verdict})
        print(f"  {game:45s} {mean_p:6.1%} {p5:6.1%} {p95:6.1%} {width:6.1%} {verdict}")

    return ci_results


# ═══════════════════════════════════════════════
# ENHANCEMENT 5: ENSEMBLE CORRELATION CHECK
# ═══════════════════════════════════════════════

def ensemble_correlation_check(lr_probs, xgb_probs, mc_probs):
    """Compute pairwise Pearson correlation between model predictions."""
    print("\n" + "=" * 60)
    print("ENSEMBLE CORRELATION CHECK")
    print("=" * 60)

    from scipy.stats import pearsonr

    models = {'LR': lr_probs, 'XGB': xgb_probs, 'MC': mc_probs}
    names = list(models.keys())

    print(f"\n  Pairwise Pearson Correlations:")
    print(f"  {'':8s}", end='')
    for n in names:
        print(f"  {n:>8s}", end='')
    print()

    flags = []
    for i, n1 in enumerate(names):
        print(f"  {n1:8s}", end='')
        for j, n2 in enumerate(names):
            if i == j:
                print(f"  {'1.000':>8s}", end='')
            else:
                r, _ = pearsonr(models[n1], models[n2])
                print(f"  {r:8.3f}", end='')
                if i < j and r > 0.90:
                    flags.append((n1, n2, r))
        print()

    if flags:
        print(f"\n  WARNING: High correlation detected (r > 0.90):")
        for n1, n2, r in flags:
            print(f"    {n1} <-> {n2}: r = {r:.3f} (models not adding diversity)")
    else:
        print(f"\n  All model pairs have r <= 0.90 — good ensemble diversity")


# ═══════════════════════════════════════════════
# ENHANCEMENT 6: STACKING META-LEARNER
# ═══════════════════════════════════════════════

def train_stacking_meta_learner(hist_df, X_clean, y_hist, clean_features, sample_weights,
                                 team_lookup, r2_matchups_df, lr_probs, xgb_probs, mc_probs,
                                 vuln_adjustments):
    """Train a logistic regression meta-learner on out-of-fold predictions."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import StratifiedKFold
    from sklearn.calibration import CalibratedClassifierCV
    import xgboost as xgb

    print("\n" + "=" * 60)
    print("STACKING META-LEARNER")
    print("=" * 60)

    try:
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        n = len(X_clean)
        oof_lr = np.zeros(n)
        oof_xgb = np.zeros(n)

        for fold, (train_idx, val_idx) in enumerate(cv.split(X_clean, y_hist)):
            X_tr, X_val = X_clean[train_idx], X_clean[val_idx]
            y_tr, y_val = y_hist[train_idx], y_hist[val_idx]
            w_tr = sample_weights[train_idx]

            # LR fold
            sc = StandardScaler()
            X_tr_s = sc.fit_transform(X_tr)
            X_val_s = sc.transform(X_val)
            lr_fold = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
            lr_fold.fit(X_tr_s, y_tr, sample_weight=w_tr)
            oof_lr[val_idx] = lr_fold.predict_proba(X_val_s)[:, 1]

            # XGB fold
            xgb_fold = xgb.XGBClassifier(
                n_estimators=200, max_depth=3, learning_rate=0.03,
                subsample=0.7, colsample_bytree=0.7,
                reg_alpha=1.0, reg_lambda=3.0,
                min_child_weight=10, gamma=0.5,
                random_state=42, eval_metric='logloss', use_label_encoder=False,
                verbosity=0,
            )
            xgb_fold.fit(X_tr, y_tr, sample_weight=w_tr)
            oof_xgb[val_idx] = xgb_fold.predict_proba(X_val)[:, 1]

        # For MC probs and vulnerability/archetype on historical data, use simple proxies
        # MC proxy: use AEM-based probability
        hist_mc = expit(0.035 * hist_df['adj_efficiency_margin_delta'].values)
        # Vulnerability proxy: 0 for historical (no R1 context)
        hist_vuln = np.zeros(n)
        # Archetype proxy: 0 for historical
        hist_arch = np.zeros(n)

        # Build meta-features
        meta_X = np.column_stack([oof_lr, oof_xgb, hist_mc, hist_vuln, hist_arch])
        meta_y = y_hist

        # Train meta-learner
        meta_model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_model.fit(meta_X, meta_y)

        print(f"  Meta-learner coefficients:")
        meta_names = ['LR_prob', 'XGB_prob', 'MC_prob', 'Vulnerability', 'Archetype']
        for name, coef in zip(meta_names, meta_model.coef_[0]):
            print(f"    {name:20s}: {coef:+.4f}")
        print(f"    {'Intercept':20s}: {meta_model.intercept_[0]:+.4f}")

        # Predict on R2 matchups
        r2_meta_X = np.column_stack([lr_probs, xgb_probs, mc_probs, vuln_adjustments, np.zeros(len(lr_probs))])
        meta_probs = meta_model.predict_proba(r2_meta_X)[:, 1]

        print(f"\n  Meta-learner R2 predictions:")
        print(f"  {'Game':45s} {'Meta':>6s} {'Old Ens':>8s} {'Diff':>6s}")
        print(f"  {'-'*70}")

        # Old ensemble for comparison
        old_ensemble = 0.40 * lr_probs + 0.40 * xgb_probs + 0.20 * mc_probs
        for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
            game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
            diff = meta_probs[i] - old_ensemble[i]
            print(f"  {game:45s} {meta_probs[i]:6.1%} {old_ensemble[i]:8.1%} {diff:+6.1%}")

        return meta_probs, meta_model

    except Exception as e:
        print(f"  ERROR in meta-learner: {e}")
        print(f"  Falling back to hardcoded ensemble weights")
        return None, None


# ═══════════════════════════════════════════════
# ENHANCEMENT 7: FEATURE INTERACTIONS
# ═══════════════════════════════════════════════

def add_interaction_features(df, clean_features):
    """Add interaction features to a dataframe. Returns updated df and updated feature list."""
    interactions = {}

    # 1. three_pt_pct_delta * variance_delta (volatile shooters)
    if 'three_pt_pct_delta' in df.columns and 'variance_delta' in df.columns:
        interactions['three_pt_x_variance'] = df['three_pt_pct_delta'].values * df['variance_delta'].values

    # 2. close_game_wpct_delta * experience_score_delta (clutch + experience)
    if 'close_game_wpct_delta' in df.columns and 'experience_score_delta' in df.columns:
        interactions['clutch_x_experience'] = df['close_game_wpct_delta'].values * df['experience_score_delta'].values

    # 3. adj_d_delta * tempo_delta (defensive team in slow game = grind)
    if 'adj_d_delta' in df.columns and 'tempo_delta' in df.columns:
        interactions['defense_x_tempo'] = df['adj_d_delta'].values * df['tempo_delta'].values

    # 4. adj_efficiency_margin_delta * round_num (AEM matters more in later rounds)
    if 'adj_efficiency_margin_delta' in df.columns and 'round_num' in df.columns:
        interactions['aem_x_round'] = df['adj_efficiency_margin_delta'].values * df['round_num'].values

    for name, vals in interactions.items():
        df[name] = vals

    new_features = clean_features + list(interactions.keys())
    return df, new_features


# ═══════════════════════════════════════════════
# ENHANCEMENT 8: CLUSTER HISTORICAL UPSETS
# ═══════════════════════════════════════════════

def cluster_historical_upsets(hist_df, r2_matchups_df, clean_features_with_interactions):
    """Cluster R32 upsets from historical data and flag R2 games near upset clusters."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    print("\n" + "=" * 60)
    print("CLUSTER ANALYSIS: HISTORICAL R32 UPSETS")
    print("=" * 60)

    # Filter to features that exist in both hist_df and r2_matchups_df
    available_features = [f for f in clean_features_with_interactions
                          if f in hist_df.columns and f in r2_matchups_df.columns]

    # Filter to R32 upsets with seed_gap > 2
    # Upset: lower seed won (team_b won when team_a was higher seed, or vice versa)
    upset_mask = (
        (hist_df['round_num'] == 2) &
        (abs(hist_df['seed_a_val'] - hist_df['seed_b_val']) > 2)
    )
    # Identify actual upsets: higher seed (worse) beat lower seed (better)
    # outcome=1 means team_a won; if seed_a > seed_b, it's an upset
    upset_a_wins = upset_mask & (hist_df['outcome'] == 1) & (hist_df['seed_a_val'] > hist_df['seed_b_val'])
    # outcome=0 means team_b won; if seed_b > seed_a, it's an upset
    upset_b_wins = upset_mask & (hist_df['outcome'] == 0) & (hist_df['seed_b_val'] > hist_df['seed_a_val'])
    full_upset_mask = upset_a_wins | upset_b_wins

    upset_df = hist_df[full_upset_mask].copy()
    print(f"  Found {len(upset_df)} R32 upsets with seed_gap > 2 in historical data")

    if len(upset_df) < 3:
        print("  Not enough upsets for clustering (need >= 3). Skipping.")
        return None

    X_upset = upset_df[available_features].values
    scaler = StandardScaler()
    X_upset_scaled = scaler.fit_transform(X_upset)

    # KMeans with k=3
    k = min(3, len(upset_df))
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    kmeans.fit(X_upset_scaled)

    print(f"\n  Cluster centers (k={k}):")
    print(f"  {'Feature':35s}", end='')
    for c in range(k):
        print(f"  {'C' + str(c):>8s}", end='')
    print()
    print(f"  {'-' * (35 + 10 * k)}")

    # Show top differentiating features per cluster
    centers = scaler.inverse_transform(kmeans.cluster_centers_)
    for j, feat in enumerate(available_features):
        vals = centers[:, j]
        if np.std(vals) > 0.01:  # Only show features with variation across clusters
            print(f"  {feat:35s}", end='')
            for c in range(k):
                print(f"  {centers[c, j]:+8.3f}", end='')
            print()

    # Label clusters
    cluster_labels = []
    for c in range(k):
        center = centers[c]
        feat_dict = {f: center[j] for j, f in enumerate(available_features)}
        label_parts = []
        if feat_dict.get('adj_d_delta', 0) < -1:
            label_parts.append("Defensive Dog")
        if feat_dict.get('three_pt_pct_delta', 0) > 0.005:
            label_parts.append("Hot Shooting")
        if feat_dict.get('experience_score_delta', 0) > 0.5:
            label_parts.append("Experienced")
        if feat_dict.get('close_game_wpct_delta', 0) > 0.05:
            label_parts.append("Clutch")
        if feat_dict.get('variance_delta', 0) > 1:
            label_parts.append("High Variance")
        label = " + ".join(label_parts) if label_parts else f"Archetype {c}"
        cluster_labels.append(label)
        print(f"\n  Cluster {c}: {label} ({(kmeans.labels_ == c).sum()} upsets)")

    # Compute distance from each R2 game to each cluster
    X_r2 = r2_matchups_df[available_features].values
    X_r2_scaled = scaler.transform(X_r2)

    print(f"\n  R2 GAMES — DISTANCE TO UPSET CLUSTERS:")
    print(f"  {'Game':45s}", end='')
    for c in range(k):
        print(f"  {'C' + str(c):>8s}", end='')
    print(f"  {'Closest':>10s}  {'Flag'}")
    print(f"  {'-'*100}")

    flagged_games = []
    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
        dists = []
        for c in range(k):
            d = np.linalg.norm(X_r2_scaled[i] - kmeans.cluster_centers_[c])
            dists.append(d)

        min_dist = min(dists)
        closest = np.argmin(dists)
        flag = "*** UPSET CLUSTER" if min_dist < 3.0 else ""

        print(f"  {game:45s}", end='')
        for d in dists:
            print(f"  {d:8.2f}", end='')
        print(f"  {'C' + str(closest):>10s}  {flag}")

        if min_dist < 3.0:
            flagged_games.append((game, closest, min_dist, cluster_labels[closest]))

    if flagged_games:
        print(f"\n  FLAGGED GAMES (close to upset cluster):")
        for game, c, d, label in flagged_games:
            print(f"    {game} -> Cluster {c} ({label}), distance={d:.2f}")

    return flagged_games


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  MARCH MADNESS 2026 — V7: ROUND 2 UPDATE")
    print("  R1 Results + Performance Signals + Re-weighted Ensemble")
    print("=" * 60)

    # ── Pull fresh data ──
    tables, sb = pull_supabase_data()

    # ── Step 1: Compute R1 performance signals ──
    r1_signals = compute_r1_performance_signals(R1_RESULTS, R1_SPREADS)

    # ── Step 2: Evaluate V6 model accuracy on R1 ──
    model_correct, total, upsets_actual, upsets_correct = evaluate_r1_accuracy(R1_RESULTS, sb)

    # ── Step 3: Update Supabase with R1 results ──
    update_supabase_r1_results(sb, R1_RESULTS)

    # Re-pull data after updates
    tables, _ = pull_supabase_data()

    # ── Build team_lookup ──
    teams_df = tables['mm_teams'].copy()
    players_df = tables['mm_players'].copy()
    teams_df = aggregate_player_features(players_df, teams_df)
    team_col = 'name' if 'name' in teams_df.columns else 'team_name'
    team_lookup = {}
    for _, row in teams_df.iterrows():
        name = row.get(team_col, '')
        seed = int(row.get('seed', 16)) if pd.notna(row.get('seed')) else 16
        adj_o = float(row.get('adj_o', 100)) if pd.notna(row.get('adj_o')) else 100.0
        adj_d = float(row.get('adj_d', 100)) if pd.notna(row.get('adj_d')) else 100.0
        cgr = str(row.get('close_game_record', '5-5'))
        cg_wpct = parse_record(cgr)
        team_lookup[name] = {
            'seed': seed,
            'kenpom_rank': int(row.get('kenpom_rank', 100)) if pd.notna(row.get('kenpom_rank')) else 100,
            'adj_o': adj_o, 'adj_d': adj_d, 'adj_efficiency_margin': adj_o - adj_d,
            'adj_tempo': float(row.get('adj_tempo', 68)) if pd.notna(row.get('adj_tempo')) else 68.0,
            'three_pt_pct': float(row.get('three_pt_pct', 0.34)) if pd.notna(row.get('three_pt_pct')) else 0.34,
            'efg_pct': float(row.get('efg_pct', 0.52)) if pd.notna(row.get('efg_pct')) else 0.52,
            'turnover_rate': float(row.get('turnover_rate', 0.16)) if pd.notna(row.get('turnover_rate')) else 0.16,
            'ft_rate': float(row.get('ft_rate', 0.34)) if pd.notna(row.get('ft_rate')) else 0.34,
            'oreb_pct': float(row.get('oreb_pct', 30.0)) if pd.notna(row.get('oreb_pct')) else 30.0,
            'conference_strength': float(row.get('conference_strength', 3.0)) if pd.notna(row.get('conference_strength')) else 3.0,
            'coach_tournament_apps': int(row.get('coach_tournament_apps', 5)) if pd.notna(row.get('coach_tournament_apps')) else 5,
            'close_game_wpct': cg_wpct,
            'performance_variance': float(row.get('performance_variance', 12.0)) if pd.notna(row.get('performance_variance')) else 12.0,
            'experience_score': float(row.get('experience_score', 5.5)) if pd.notna(row.get('experience_score')) else 5.5,
            'win_pct': parse_record(row.get('record', '20-10')),
            'last_10_win_pct': parse_record(row.get('last_10_record', '5-5')),
            'draft_prospects': int(row.get('draft_prospects', 0)) if pd.notna(row.get('draft_prospects')) else 0,
            'conference': str(row.get('conference', '')),
        }

    # ── Enhancement 1: Bayesian update of team AEM from R1 results ──
    team_lookup = bayesian_update_team_lookup(team_lookup, R1_RESULTS, R1_SPREADS)

    # ── Step 4: Build R2 features (now uses Bayesian-updated team_lookup) ──
    r2_matchups_df = build_r2_features(tables, r1_signals, team_lookup)

    # ── Train models with CLEANED features (multicollinearity removed) ──
    hist_df = load_historical_data()

    # Remove multicollinear features:
    # - seed_delta, seed_a_val, seed_b_val, hist_seed_win_rate: all r>0.86 with each other (seed x4)
    # - adj_o_delta: AEM = adj_o - adj_d, so having all 3 triple-counts (VIF=inf)
    # - kenpom_rank_delta: r=0.79 with AEM delta (VIF=25)
    CLEAN_FEATURES = [f for f in SHARED_FEATURES if f not in [
        'seed_delta', 'seed_a_val', 'seed_b_val', 'hist_seed_win_rate',
        'adj_o_delta', 'kenpom_rank_delta',
    ]]

    print("\n" + "=" * 60)
    print("CLEANED FEATURE SET (multicollinearity removed)")
    print("=" * 60)
    print(f"  Original: {len(SHARED_FEATURES)} features")
    print(f"  Cleaned:  {len(CLEAN_FEATURES)} features")
    print(f"  Removed:  seed_delta, seed_a/b_val, hist_seed_win_rate, adj_o_delta, kenpom_rank_delta")
    print(f"  Kept:     adj_efficiency_margin_delta (quality gap)")
    print(f"            adj_d_delta (defensive matchup)")
    print(f"            higher_seed_kenpom, aem_sum (absolute quality context)")
    print(f"            + all matchup features: 3pt%, eFG%, TO, FT, OREB, close games, tempo, etc.")

    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    # ── Enhancement 7: Add interaction features to hist_df and r2_matchups_df ──
    hist_df, CLEAN_FEATURES_INTERACT = add_interaction_features(hist_df, CLEAN_FEATURES)
    r2_matchups_df, _ = add_interaction_features(r2_matchups_df, CLEAN_FEATURES)

    print(f"\n  Added {len(CLEAN_FEATURES_INTERACT) - len(CLEAN_FEATURES)} interaction features:")
    for f in CLEAN_FEATURES_INTERACT:
        if f not in CLEAN_FEATURES:
            print(f"    + {f}")

    # Use interaction features for training
    CLEAN_FEATURES_FINAL = CLEAN_FEATURES_INTERACT

    X_clean = hist_df[CLEAN_FEATURES_FINAL].values
    y_hist = hist_df['outcome'].values
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # ── Enhancement 2: Compute recency weights ──
    sample_weights = compute_recency_weights(hist_df)

    # ── LR v2: trained on clean features with recency weights ──
    print("\n  --- LR v2 (clean features + interactions + recency weights) ---")
    scaler_v2 = StandardScaler()
    X_clean_scaled = scaler_v2.fit_transform(X_clean)
    base_lr_v2 = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
    lr_v2 = CalibratedClassifierCV(base_lr_v2, method='sigmoid', cv=5)
    auc_lr2 = cross_val_score(base_lr_v2, X_clean_scaled, y_hist, cv=cv, scoring='roc_auc')
    print(f"  5-Fold AUC: {auc_lr2.mean():.4f} (+/- {auc_lr2.std():.4f})")
    lr_v2.fit(X_clean_scaled, y_hist, sample_weight=sample_weights)

    # Show LR coefficients — now we can see what actually matters
    base_lr_v2.fit(X_clean_scaled, y_hist, sample_weight=sample_weights)
    print("\n  LR v2 Top coefficients (what actually drives predictions):")
    coefs = base_lr_v2.coef_[0]
    for i in np.argsort(np.abs(coefs))[::-1][:10]:
        print(f"    {CLEAN_FEATURES_FINAL[i]:35s} {coefs[i]:+.4f}")

    # ── XGB v2: trained on clean features with recency weights ──
    print("\n  --- XGB v2 (clean features + interactions + recency weights) ---")
    xgb_base_v2 = xgb.XGBClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.03,
        subsample=0.7, colsample_bytree=0.7,
        reg_alpha=1.0, reg_lambda=3.0,
        min_child_weight=10, gamma=0.5,
        random_state=42, eval_metric='logloss', use_label_encoder=False,
    )
    xgb_v2 = CalibratedClassifierCV(xgb_base_v2, method='isotonic', cv=5)
    auc_xgb2 = cross_val_score(xgb_base_v2, X_clean, y_hist, cv=cv, scoring='roc_auc')
    print(f"  5-Fold AUC: {auc_xgb2.mean():.4f} (+/- {auc_xgb2.std():.4f})")
    xgb_v2.fit(X_clean, y_hist, sample_weight=sample_weights)

    xgb_base_v2.fit(X_clean, y_hist, sample_weight=sample_weights)
    print("\n  XGB v2 Top features:")
    imp = xgb_base_v2.feature_importances_
    for i in np.argsort(imp)[::-1][:10]:
        print(f"    {CLEAN_FEATURES_FINAL[i]:35s} {imp[i]:.4f}")

    # Output range comparison
    print("\n  Output ranges on training data:")
    lr_train = lr_v2.predict_proba(X_clean_scaled)[:, 1]
    xgb_train = xgb_v2.predict_proba(X_clean)[:, 1]
    print(f"    LR v2:  [{lr_train.min():.3f}, {lr_train.max():.3f}] std={lr_train.std():.3f}")
    print(f"    XGB v2: [{xgb_train.min():.3f}, {xgb_train.max():.3f}] std={xgb_train.std():.3f}")

    # Also train old V5 models for comparison (uses SHARED_FEATURES with multicollinearity)
    lr_v5, xgb_model_v5, scaler_v5 = train_models(hist_df)

    # ── Step 5: Predict R2 with ensemble ──
    print("\n" + "=" * 60)
    print("R2 ENSEMBLE PREDICTIONS")
    print("=" * 60)

    # V5 models (old, for comparison)
    X_shared = r2_matchups_df[SHARED_FEATURES].values
    X_v5_scaled = scaler_v5.transform(X_shared)
    xgb_v1_probs = xgb_model_v5.predict_proba(X_shared)[:, 1]

    # V2 clean models (with interaction features)
    X_r2_clean = r2_matchups_df[CLEAN_FEATURES_FINAL].values
    X_r2_clean_scaled = scaler_v2.transform(X_r2_clean)
    lr_probs = lr_v2.predict_proba(X_r2_clean_scaled)[:, 1]
    xgb_probs = xgb_v2.predict_proba(X_r2_clean)[:, 1]
    mc_probs = r2_matchups_df.apply(monte_carlo_prob, axis=1).values

    # Print old vs new model comparison
    lr_v1_probs = lr_v5.predict_proba(X_v5_scaled)[:, 1]
    print("\n  V5 (old) vs V2 (clean) on R2 matchups:")
    print(f"  {'Game':40s} {'LRv1':>5s} {'LRv2':>5s} {'XGBv1':>6s} {'XGBv2':>6s}")
    print(f"  {'-'*65}")
    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
        print(f"  {game:40s} {lr_v1_probs[i]:5.0%} {lr_probs[i]:5.0%} {xgb_v1_probs[i]:6.0%} {xgb_probs[i]:6.0%}")

    # ══════════════════════════════════════════════════════
    # ENSEMBLE WITH VULNERABILITY + ARCHETYPE SCORING
    # ══════════════════════════════════════════════════════

    # Step A: Compute upset vulnerability score per game
    # (from historical analysis: what features separate upsets from chalk)
    print(f"\n  UPSET VULNERABILITY + ARCHETYPE ANALYSIS:")
    print(f"  {'Game':40s} {'Vuln%':>6s} {'Arch':>5s} {'Adj':>8s}")
    print(f"  {'-'*65}")

    EXPECTED_KP = {1:4, 2:12, 3:18, 4:24, 5:30, 6:35, 7:40, 8:45, 9:50,
                   10:55, 11:55, 12:65, 13:80, 14:100, 15:130, 16:160}

    vuln_adjustments = np.zeros(len(lr_probs))

    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        sa_ = int(row['_seed_a'])
        sb_ = int(row['_seed_b'])
        seed_gap = abs(sb_ - sa_)
        ta = team_lookup.get(row['_team_a'], {})
        tb = team_lookup.get(row['_team_b'], {})
        game = f"({sa_}) {row['_team_a']} vs ({sb_}) {row['_team_b']}"

        # --- Vulnerability score (how weak is the favorite?) ---
        aem_a = ta.get('adj_efficiency_margin', ta.get('adj_o', 100) - ta.get('adj_d', 100))
        aem_b = tb.get('adj_efficiency_margin', tb.get('adj_o', 100) - tb.get('adj_d', 100))
        aem_delta = aem_a - aem_b
        kp_fav = ta.get('kenpom_rank', 50)
        fav_kp_gap = EXPECTED_KP.get(sa_, 50) - kp_fav  # positive = fav better than seed
        dog_kp_gap = EXPECTED_KP.get(sb_, 50) - tb.get('kenpom_rank', 50)

        # Vulnerability: higher = more likely upset
        # Driven by: small AEM gap, favorite overseeded, underdog underseeded
        vuln_raw = 0.0
        if aem_delta < 2.0:
            vuln_raw += 0.15  # teams are basically even or underdog is better
        if aem_delta < 0:
            vuln_raw += 0.10  # underdog is actually BETTER
        if dog_kp_gap > 10:
            vuln_raw += 0.05  # underdog much better than seed suggests
        if fav_kp_gap < -5:
            vuln_raw += 0.05  # favorite worse than seed suggests

        # --- Archetype score (does underdog fit the R32 upset profile?) ---
        arch_score = 0.0

        if seed_gap > 2:
            # 1. Tempo mismatch
            tempo_mismatch = abs(ta.get('adj_tempo', 68) - tb.get('adj_tempo', 68))
            if tempo_mismatch > 3.0:
                arch_score += 0.06
            elif tempo_mismatch > 1.5:
                arch_score += 0.03

            # 2. Close game edge for underdog
            cg_a = ta.get('close_game_wpct', 0.5)
            cg_b = tb.get('close_game_wpct', 0.5)
            if cg_b > cg_a:
                arch_score += 0.06  # underdog is more clutch
            elif cg_b > cg_a - 0.05:
                arch_score += 0.03  # roughly even in close games

            # 3. Three-point shooting edge
            tpt_a = ta.get('three_pt_pct', 0.34)
            tpt_b = tb.get('three_pt_pct', 0.34)
            if tpt_b > tpt_a:
                arch_score += 0.06  # underdog shoots better from 3
            elif tpt_b > tpt_a - 0.005:
                arch_score += 0.03

            # 4. Seed-KenPom mismatch (underdog outperforms seed)
            if dog_kp_gap > 15:
                arch_score += 0.06
            elif dog_kp_gap > 5:
                arch_score += 0.03

        # Total adjustment: subtract from favorite's probability
        total_adj = vuln_raw + arch_score

        # For 4v5 games (seed_gap <=2), vulnerability still applies but no archetype
        # For big-gap games, both apply
        vuln_adjustments[i] = total_adj

        if total_adj > 0.01:
            print(f"  {game:40s} {vuln_raw:5.0%} {arch_score:5.0%} {total_adj:+7.0%}")

    # ── Enhancement 5: Ensemble correlation check ──
    ensemble_correlation_check(lr_probs, xgb_probs, mc_probs)

    # Step B: Base ensemble (LR + XGBv2 + MC, no Vegas for R2)
    w_lr_r2 = 0.40
    w_xgb_r2 = 0.40
    w_mc_r2 = 0.20

    print(f"\n  R2 ENSEMBLE WEIGHTS (stat models only, no seed crutches):")
    print(f"    LR:    {w_lr_r2:.0%}")
    print(f"    XGBv2: {w_xgb_r2:.0%}")
    print(f"    MC:    {w_mc_r2:.0%}")
    print(f"    + vulnerability/archetype adjustments applied post-ensemble")

    # Print per-game model comparison
    print(f"\n  PER-GAME MODEL COMPARISON:")
    print(f"  {'Game':40s} {'LR':>5s} {'XGBv2':>6s} {'MC':>5s} {'V+A adj':>8s}")
    print(f"  {'-'*70}")
    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        game = f"({int(row['_seed_a'])}) {row['_team_a']} vs ({int(row['_seed_b'])}) {row['_team_b']}"
        print(f"  {game:40s} {lr_probs[i]:5.0%} {xgb_probs[i]:6.0%} {mc_probs[i]:5.0%} {vuln_adjustments[i]:+7.0%}")

    # ── SKIP meta-learner: it re-learned seed bias and pulled everything back to chalk ──
    # Instead: use base ensemble + vulnerability/archetype + archetype-based upset picks
    print("\n  Using BASE ENSEMBLE + ARCHETYPE UPSET PICKS (no meta-learner)")
    ensemble_a = w_lr_r2 * lr_probs + w_xgb_r2 * xgb_probs + w_mc_r2 * mc_probs
    ensemble_a = ensemble_a - vuln_adjustments

    # ── ARCHETYPE UPSET PICKS ──
    # For big seed gap games (>2), the archetype analysis identified which games
    # fit the historical R32 upset profile. For games that score >= 0.55 on the
    # archetype, AND the base ensemble has the favorite < 70%, we flip to the underdog.
    #
    # This is a BRACKET STRATEGY decision, not a probability claim.
    # In a bracket pool, you need contrarian picks where you have analytical backing.

    EXPECTED_KP = {1:4, 2:12, 3:18, 4:24, 5:30, 6:35, 7:40, 8:45, 9:50,
                   10:55, 11:55, 12:65, 13:80, 14:100, 15:130, 16:160}

    print(f"\n  ARCHETYPE-DRIVEN UPSET FLIPS:")
    print(f"  {'-'*70}")
    for i, (_, row) in enumerate(r2_matchups_df.iterrows()):
        sa_ = int(row['_seed_a'])
        sb_ = int(row['_seed_b'])
        seed_gap = abs(sb_ - sa_)
        if seed_gap <= 2:
            continue

        ta = team_lookup.get(row['_team_a'], {})
        tb = team_lookup.get(row['_team_b'], {})

        # Compute archetype score (same logic as our analysis)
        tempo_mismatch = abs(ta.get('adj_tempo', 68) - tb.get('adj_tempo', 68))
        tempo_score = min(tempo_mismatch / 5.0, 1.0)

        cg_a = ta.get('close_game_wpct', 0.5)
        cg_b = tb.get('close_game_wpct', 0.5)
        cg_score = max(0, min(1.0, ((cg_b - cg_a) + 0.1) / 0.3))

        tpt_edge = tb.get('three_pt_pct', 0.34) - ta.get('three_pt_pct', 0.34)
        tpt_score = max(0, min(1.0, (tpt_edge + 0.02) / 0.04))

        dog_kp_gap = EXPECTED_KP.get(sb_, 50) - tb.get('kenpom_rank', 50)
        fav_kp_gap = EXPECTED_KP.get(sa_, 50) - ta.get('kenpom_rank', 50)
        skp_mismatch = dog_kp_gap - fav_kp_gap
        skp_score = max(0, min(1.0, (skp_mismatch + 10) / 30))

        arch = 0.30 * tempo_score + 0.25 * cg_score + 0.25 * tpt_score + 0.20 * skp_score

        game = f"({sa_}) {row['_team_a']} vs ({sb_}) {row['_team_b']}"

        # Flip threshold: archetype >= 0.55 AND ensemble has favorite < 72%
        if arch >= 0.55 and ensemble_a[i] < 0.72:
            old_prob = ensemble_a[i]
            # Flip: set underdog probability to 0.52-0.58 based on archetype strength
            flip_prob = 0.50 - (arch - 0.55) * 0.5  # higher archetype = more confident upset
            ensemble_a[i] = flip_prob
            print(f"  FLIP: {game:40s} arch={arch:.2f} {old_prob:.1%} -> {flip_prob:.1%} (pick underdog)")
        elif arch >= 0.40:
            print(f"  WATCH: {game:40s} arch={arch:.2f} ens={ensemble_a[i]:.1%} (close but held)")
        else:
            print(f"  SAFE:  {game:40s} arch={arch:.2f} ens={ensemble_a[i]:.1%}")

    ensemble_a = np.nan_to_num(ensemble_a, nan=0.5)
    ensemble_a = np.clip(ensemble_a, 0.02, 0.98)
    ensemble_b = 1 - ensemble_a

    def get_tier(p):
        m = max(p, 1-p)
        if m > 0.75: return 'LOCK'
        elif m > 0.65: return 'STRONG'
        elif m > 0.55: return 'LEAN'
        else: return 'TOSS-UP'

    results_df = r2_matchups_df[['_team_a', '_team_b', '_round', '_region', '_seed_a', '_seed_b']].copy()
    results_df['lr_prob_a'] = np.round(lr_probs, 4)
    results_df['xgb_v1_prob_a'] = np.round(xgb_v1_probs, 4)
    results_df['xgb_prob_a'] = np.round(xgb_probs, 4)
    results_df['vegas_prob_a'] = 0.5  # no vegas for R2
    results_df['agent_prob_a'] = 0.5  # agent removed
    results_df['mc_prob_a'] = np.round(mc_probs, 4)
    results_df['ensemble_prob_a'] = np.round(ensemble_a, 4)
    results_df['ensemble_prob_b'] = np.round(ensemble_b, 4)
    results_df['pick'] = results_df.apply(
        lambda r: r['_team_a'] if r['ensemble_prob_a'] >= 0.5 else r['_team_b'], axis=1)
    results_df['pick_confidence'] = np.round(np.maximum(ensemble_a, ensemble_b), 4)
    results_df['confidence_tier'] = results_df['pick_confidence'].apply(get_tier)

    # Add R1 signal columns for upset adjustment
    for col in ['r1_margin_vs_spread_a', 'r1_margin_vs_spread_b', 'r1_scare_factor_a',
                'r1_scare_factor_b', 'r1_dominance_score_a', 'r1_dominance_score_b',
                'r1_upset_winner_a', 'r1_upset_winner_b', 'r1_blowout_winner_a',
                'r1_blowout_winner_b', 'r1_close_game_survivor_a', 'r1_close_game_survivor_b',
                'agent_uncertainty']:
        if col in r2_matchups_df.columns:
            results_df[col] = r2_matchups_df[col].values

    # ── Apply upset classifier ──
    print("\n  Training upset classifier for R2...")
    upset_df = generate_upset_training_data(n_tournaments=30)
    upset_model = train_upset_model(upset_df)

    # Apply upset adjustments
    upset_probs = []
    adjusted_ensemble = results_df['ensemble_prob_a'].values.copy()
    for idx, row in results_df.iterrows():
        sa, sb_val = int(row['_seed_a']), int(row['_seed_b'])
        ta = team_lookup.get(row['_team_a'], {})
        tb = team_lookup.get(row['_team_b'], {})

        if sa == sb_val:
            upset_probs.append(0.0)
            continue

        if sa < sb_val:
            fav, dog = ta, tb
            ensemble_fav = row['ensemble_prob_a']
            is_a_favorite = True
        else:
            fav, dog = tb, ta
            ensemble_fav = row['ensemble_prob_b']
            is_a_favorite = False

        vegas_fav = ensemble_fav  # No vegas for R2
        uf = compute_upset_features_from_teams(
            fav, dog,
            agent_uncertainty=row.get('agent_uncertainty', 0.15) if not pd.isna(row.get('agent_uncertainty', 0.15)) else 0.15,
            vegas_fav_prob=vegas_fav,
        )
        X_upset = np.array([[uf[f] for f in UPSET_FEATURES]])
        up = upset_model.predict_proba(X_upset)[0, 1]
        upset_probs.append(round(up, 4))

        # Soften overconfident chalk
        if up > 0.35 and ensemble_fav > 0.55:
            max_adj = (ensemble_fav - 0.50) * 0.5
            adj = max_adj * (up - 0.35) / 0.65
            loc = results_df.index.get_loc(idx)
            if is_a_favorite:
                adjusted_ensemble[loc] -= adj
            else:
                adjusted_ensemble[loc] += adj

    results_df['upset_probability'] = upset_probs
    results_df['ensemble_prob_a'] = np.clip(adjusted_ensemble, 0.02, 0.98)
    results_df['ensemble_prob_b'] = 1 - results_df['ensemble_prob_a']
    results_df['pick'] = results_df.apply(
        lambda r: r['_team_a'] if r['ensemble_prob_a'] >= 0.5 else r['_team_b'], axis=1)
    results_df['pick_confidence'] = np.maximum(results_df['ensemble_prob_a'], results_df['ensemble_prob_b'])
    results_df['confidence_tier'] = results_df['pick_confidence'].apply(get_tier)

    # ── Apply R2-specific adjustments ──
    results_df = apply_r2_adjustments(results_df, r1_signals)

    # ── Print full R2 bracket ──
    print("\n" + "=" * 60)
    print("  R2 BRACKET PREDICTIONS (Round of 32)")
    print("=" * 60)

    for region in ['East', 'West', 'Midwest', 'South']:
        rg = results_df[results_df['_region'] == region]
        if len(rg) == 0:
            continue
        print(f"\n  {'─'*55}")
        print(f"  {region} Region")
        print(f"  {'─'*55}")
        for _, g in rg.iterrows():
            marker = {'LOCK': '***', 'STRONG': '**', 'LEAN': '*'}.get(g['confidence_tier'], '')
            upset_str = f"UP={g.get('upset_probability', 0):.0%}" if g.get('upset_probability', 0) > 0.25 else ""
            print(f"  ({g['_seed_a']:>2}) {g['_team_a']:18s} vs ({g['_seed_b']:>2}) {g['_team_b']:18s} "
                  f"-> {g['pick']:18s} [{g['confidence_tier']:7s}] "
                  f"({g['ensemble_prob_a']:.1%}/{g['ensemble_prob_b']:.1%}) "
                  f"LR={g['lr_prob_a']:.0%} XGBv1={g.get('xgb_v1_prob_a', 0):.0%} XGBv2={g['xgb_prob_a']:.0%} {upset_str} {marker}")

    # ── Upset Watch ──
    print("\n" + "=" * 60)
    print("  R2 UPSET WATCH")
    print("=" * 60)
    upset_sorted = results_df.sort_values('upset_probability', ascending=False)
    print(f"\n  {'Game':45s} {'Upset%':>6s} {'Ens%':>6s} {'Pick':>18s}")
    print(f"  {'-'*80}")
    for _, g in upset_sorted.iterrows():
        fav_seed = min(g['_seed_a'], g['_seed_b'])
        dog_seed = max(g['_seed_a'], g['_seed_b'])
        fav = g['_team_a'] if g['_seed_a'] == fav_seed else g['_team_b']
        dog = g['_team_a'] if g['_seed_a'] == dog_seed else g['_team_b']
        ens_fav = g['ensemble_prob_a'] if g['_seed_a'] == fav_seed else g['ensemble_prob_b']
        print(f"  ({fav_seed:>2}) {fav:18s} vs ({dog_seed:>2}) {dog:18s} "
              f"{g['upset_probability']:6.0%} {ens_fav:6.1%} {g['pick']:>18s}")

    # ── R2 Under Candidates ──
    print("\n" + "=" * 60)
    print("  R2 UNDER CANDIDATES (tempo/defense matchups)")
    print("=" * 60)
    under_scores = []
    for _, g in results_df.iterrows():
        ta = team_lookup.get(g['_team_a'], {})
        tb = team_lookup.get(g['_team_b'], {})
        # Low tempo + good defense = under
        avg_tempo = (ta.get('adj_tempo', 68) + tb.get('adj_tempo', 68)) / 2
        avg_def = (ta.get('adj_d', 95) + tb.get('adj_d', 95)) / 2
        under_score = (68 - avg_tempo) + (avg_def - 95) * 0.5  # higher = more likely under
        under_scores.append({
            'game': f"({g['_seed_a']}) {g['_team_a']} vs ({g['_seed_b']}) {g['_team_b']}",
            'avg_tempo': avg_tempo,
            'avg_def': avg_def,
            'under_score': under_score,
            'region': g['_region'],
        })
    under_df = pd.DataFrame(under_scores).sort_values('under_score', ascending=False)
    print(f"\n  {'Game':50s} {'Tempo':>6s} {'Def':>6s} {'Under Score':>11s}")
    print(f"  {'-'*80}")
    for _, u in under_df.head(6).iterrows():
        print(f"  {u['game']:50s} {u['avg_tempo']:6.1f} {u['avg_def']:6.1f} {u['under_score']:+11.1f}")

    # ── Enhancement 3: SHAP values per game ──
    compute_shap_values(xgb_base_v2, X_r2_clean, r2_matchups_df, CLEAN_FEATURES_FINAL)

    # ── Enhancement 4: Bootstrap confidence intervals ──
    bootstrap_confidence_intervals(
        X_clean, y_hist, X_r2_clean,
        lambda x: scaler_v2.transform(x),
        r2_matchups_df, CLEAN_FEATURES_FINAL, n_boot=200,
    )

    # ── Enhancement 8: Cluster historical upsets ──
    cluster_historical_upsets(hist_df, r2_matchups_df, CLEAN_FEATURES_FINAL)

    # ── Simulation ──
    sim_df = simulate_r2_bracket(results_df, team_lookup, r1_signals)

    # ── Write to Supabase ──
    write_r2_to_supabase(sb, results_df, sim_df)

    # ── Final Summary ──
    print("\n" + "=" * 60)
    print("  V7 R2 UPDATE COMPLETE!")
    print("=" * 60)

    f4 = sim_df.nlargest(4, 'prob_f4')
    print(f"\n  MOST LIKELY FINAL FOUR:")
    for _, t in f4.iterrows():
        print(f"    ({t['seed']}) {t['team']} — {t['prob_f4']:.1%}")

    ch = sim_df.iloc[0]
    print(f"\n  PREDICTED CHAMPION: ({ch['seed']}) {ch['team']} — {ch['prob_winner']:.1%}")


if __name__ == '__main__':
    main()
