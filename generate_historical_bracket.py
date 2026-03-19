#!/usr/bin/env python3
"""
Generate the HISTORICAL_MODEL_BRACKET.md using the V5 pipeline trained on real data.
Uses the same upset-target approach from the final bracket.
"""

import os, sys, json, warnings
import numpy as np
import pandas as pd
from collections import Counter
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score
import xgboost as xgb
from supabase import create_client

warnings.filterwarnings('ignore')
np.random.seed(42)

# Import everything from the main pipeline
sys.path.insert(0, os.path.dirname(__file__))
from bracket_predictor import (
    SUPABASE_URL, SUPABASE_KEY, SHARED_FEATURES, ROUND_MAP,
    HIST_SEED_WIN_RATE, AEM_BY_SEED, KENPOM_RANK_BY_SEED, EXPECTED_KENPOM,
    CONF_STRENGTH_BY_SEED, COACH_APPS_BY_SEED,
    CEILING_F4, CEILING_CHAMP, CEILING_WINNER,
    SEED_REGRESSION_WEIGHT,
    W_LR, W_XGB, W_VEGAS, W_AGENT, W_MC,
    BREAKING_NEWS, N_SIMULATIONS,
    parse_record, parse_streak, get_hist_seed_win_rate,
    moneyline_to_prob, compute_delta_features,
    pull_supabase_data, aggregate_player_features, build_2026_features,
    load_historical_data, train_models,
    vegas_prob, agent_swarm_prob, monte_carlo_prob,
    predict_ensemble,
)

# Upset targets per round
UPSET_TARGETS = {
    'R64': 7, 'R32': 3, 'S16': 1, 'E8': 1, 'F4': 0, 'NCG': 0
}

# Protect seeds from upset flipping
PROTECTED_SEEDS_R32 = {1, 2}     # R32: protect 1 and 2 seeds
PROTECTED_SEEDS_S16 = {1}         # S16: only protect 1 seeds
PROTECTED_SEEDS_LATE = set()      # E8+: no protection (let upsets happen)


def build_bracket_with_upsets(results_df, team_lookup):
    """Build a deterministic bracket using ensemble probabilities + upset targets.

    Strategy:
    1. Start with model's default picks (by ensemble probability)
    2. Count how many of those are already upsets (lower seed winning)
    3. If fewer than target, flip the most likely additional upsets
    4. Protect 1-seeds and 2-seeds from being upset in R32+
    """

    # Parse results into a structured bracket
    bracket = {}
    for _, row in results_df.iterrows():
        rnd = row['_round']
        if rnd not in bracket:
            bracket[rnd] = []
        bracket[rnd].append({
            'team_a': row['_team_a'],
            'team_b': row['_team_b'],
            'seed_a': int(row['_seed_a']),
            'seed_b': int(row['_seed_b']),
            'region': row['_region'],
            'prob_a': float(row['ensemble_prob_a']),
            'prob_b': float(row['ensemble_prob_b']),
            'lr_prob_a': float(row['lr_prob_a']),
            'xgb_prob_a': float(row['xgb_prob_a']),
            'vegas_prob_a': float(row['vegas_prob_a']),
            'agent_prob_a': float(row['agent_prob_a']),
            'confidence': float(row['pick_confidence']),
            'tier': row['confidence_tier'],
        })

    all_picks = {}

    for rnd in ['R64', 'R32', 'S16', 'E8', 'F4', 'NCG']:
        if rnd not in bracket:
            continue
        games = bracket[rnd]
        n_upset_target = UPSET_TARGETS.get(rnd, 0)

        # For each game, compute metadata
        game_info = []
        for g in games:
            # Determine who is the higher seed (favorite by seed)
            if g['seed_a'] < g['seed_b']:
                fav_team, und_team = g['team_a'], g['team_b']
                fav_seed, und_seed = g['seed_a'], g['seed_b']
                upset_prob = g['prob_b']  # prob underdog wins
            elif g['seed_a'] > g['seed_b']:
                fav_team, und_team = g['team_b'], g['team_a']
                fav_seed, und_seed = g['seed_b'], g['seed_a']
                upset_prob = g['prob_a']
            else:
                # Same seed: no upset possible
                fav_team, und_team = g['team_a'], g['team_b']
                fav_seed, und_seed = g['seed_a'], g['seed_b']
                upset_prob = g['prob_b']

            # Model's default pick
            default_pick = g['team_a'] if g['prob_a'] >= 0.5 else g['team_b']
            default_pick_seed = g['seed_a'] if default_pick == g['team_a'] else g['seed_b']

            # Is the default pick already an upset?
            is_default_upset = (default_pick_seed > fav_seed) and (fav_seed != und_seed)

            game_info.append({
                **g,
                'fav_team': fav_team, 'und_team': und_team,
                'fav_seed': fav_seed, 'und_seed': und_seed,
                'upset_prob': upset_prob,
                'default_pick': default_pick,
                'is_default_upset': is_default_upset,
            })

        # Count existing upsets in default picks
        existing_upsets = [gi for gi in game_info if gi['is_default_upset']]
        n_existing = len(existing_upsets)

        if n_existing < n_upset_target:
            # Need MORE upsets: flip some favorite picks to underdog
            needed_flips = n_upset_target - n_existing
            flip_candidates = [
                gi for gi in game_info
                if not gi['is_default_upset']
                and gi['fav_seed'] != gi['und_seed']
                and gi['upset_prob'] > 0.20
            ]
            if rnd == 'R32':
                flip_candidates = [gi for gi in flip_candidates if gi['fav_seed'] not in PROTECTED_SEEDS_R32]
            elif rnd in ('S16', 'E8', 'F4', 'NCG'):
                flip_candidates = [gi for gi in flip_candidates if gi['fav_seed'] not in PROTECTED_SEEDS_LATE]
            flip_candidates.sort(key=lambda x: x['upset_prob'], reverse=True)
            games_to_upset = set()
            for i, gi in enumerate(flip_candidates):
                if i >= needed_flips:
                    break
                games_to_upset.add((gi['team_a'], gi['team_b']))
            games_to_revert = set()

        elif n_existing > n_upset_target:
            # Too MANY upsets: revert the least likely ones back to favorites
            excess = n_existing - n_upset_target
            # Sort existing upsets by upset_prob ascending (least likely first = revert first)
            revert_candidates = sorted(existing_upsets, key=lambda x: x['upset_prob'])
            # In R32+, don't protect reverting TO the favorite (that's always safe)
            games_to_revert = set()
            for i, gi in enumerate(revert_candidates):
                if i >= excess:
                    break
                games_to_revert.add((gi['team_a'], gi['team_b']))
            games_to_upset = set()
        else:
            games_to_upset = set()
            games_to_revert = set()

        # Build final picks
        round_picks = []
        for gi in game_info:
            key = (gi['team_a'], gi['team_b'])
            if key in games_to_upset:
                # Force upset: pick the underdog
                pick = gi['und_team']
            elif key in games_to_revert:
                # Revert to favorite
                pick = gi['fav_team']
            else:
                # Use model's default pick
                pick = gi['default_pick']

            pick_seed = gi['seed_a'] if pick == gi['team_a'] else gi['seed_b']
            is_upset = (pick_seed > gi['fav_seed']) and (gi['fav_seed'] != gi['und_seed'])

            round_picks.append({
                **{k: v for k, v in gi.items() if k in ('team_a', 'team_b', 'seed_a', 'seed_b', 'region', 'prob_a', 'prob_b', 'confidence', 'tier')},
                'pick': pick,
                'is_upset': is_upset,
            })

        all_picks[rnd] = round_picks

    return all_picks


def format_bracket_md(all_picks):
    """Format the bracket as markdown."""

    lines = []
    lines.append("# 2026 NCAA Tournament Bracket — Historical Model Prediction")
    lines.append("")

    # Find champion
    if 'NCG' in all_picks and all_picks['NCG']:
        ncg = all_picks['NCG'][0]
        champ = ncg['pick']
        champ_seed = ncg['seed_a'] if ncg['pick'] == ncg['team_a'] else ncg['seed_b']
        lines.append(f"## Champion: ({champ_seed}) {champ}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # R64
    lines.append("### ROUND OF 64")
    lines.append("")
    regions_r64 = {}
    for p in all_picks.get('R64', []):
        r = p['region']
        if r not in regions_r64:
            regions_r64[r] = []
        regions_r64[r].append(p)

    for region in sorted(regions_r64.keys()):
        lines.append(f"#### {region} Region")
        lines.append("| Matchup | Pick |")
        lines.append("|---------|------|")
        for p in regions_r64[region]:
            pick_bold = f"**{p['pick']}**"
            lines.append(f"| ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} | {pick_bold} |")
        lines.append("")

    # R32
    lines.append("### ROUND OF 32")
    lines.append("")
    regions_r32 = {}
    for p in all_picks.get('R32', []):
        r = p['region']
        if r not in regions_r32:
            regions_r32[r] = []
        regions_r32[r].append(p)

    for region in sorted(regions_r32.keys()):
        lines.append(f"#### {region}")
        lines.append("| Matchup | Pick |")
        lines.append("|---------|------|")
        for p in regions_r32[region]:
            pick_bold = f"**{p['pick']}**"
            lines.append(f"| ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} | {pick_bold} |")
        lines.append("")

    # S16
    lines.append("### SWEET 16")
    lines.append("")
    lines.append("| Region | Matchup | Pick |")
    lines.append("|--------|---------|------|")
    for p in all_picks.get('S16', []):
        pick_bold = f"**{p['pick']}**"
        lines.append(f"| {p['region']} | ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} | {pick_bold} |")
    lines.append("")

    # E8
    lines.append("### ELITE 8")
    lines.append("")
    lines.append("| Region | Matchup | Pick |")
    lines.append("|--------|---------|------|")
    for p in all_picks.get('E8', []):
        pick_bold = f"**{p['pick']}**"
        lines.append(f"| {p['region']} | ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} | {pick_bold} |")
    lines.append("")

    # F4
    lines.append("### FINAL FOUR")
    lines.append("")
    lines.append("| Matchup | Pick |")
    lines.append("|---------|------|")
    for p in all_picks.get('F4', []):
        pick_bold = f"**{p['pick']}**"
        lines.append(f"| ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} | {pick_bold} |")
    lines.append("")

    # NCG
    lines.append("### NATIONAL CHAMPIONSHIP")
    lines.append("")
    lines.append("| Matchup | Pick |")
    lines.append("|---------|------|")
    for p in all_picks.get('NCG', []):
        pick_bold = f"**{p['pick']}**"
        lines.append(f"| **(1) {p['team_a']} vs (1) {p['team_b']}** | {pick_bold} |")
    lines.append("")

    # Upset Summary
    lines.append("---")
    lines.append("")
    lines.append("## Upset Summary")
    lines.append("")

    total_upsets = 0
    for rnd_name, rnd_key in [('R64', 'R64'), ('R32', 'R32'), ('S16', 'S16'), ('E8', 'E8'), ('F4', 'F4'), ('NCG', 'NCG')]:
        upsets = [p for p in all_picks.get(rnd_key, []) if p.get('is_upset', False)]
        if upsets:
            lines.append(f"### {rnd_name} Upsets ({len(upsets)})")
            for i, p in enumerate(upsets, 1):
                pick = p['pick']
                pick_seed = p['seed_a'] if pick == p['team_a'] else p['seed_b']
                loser = p['team_b'] if pick == p['team_a'] else p['team_a']
                loser_seed = p['seed_b'] if pick == p['team_a'] else p['seed_a']
                lines.append(f"{i}. ({pick_seed}) {pick} over ({loser_seed}) {loser}")
            lines.append("")
            total_upsets += len(upsets)

    lines.append(f"### Total: {total_upsets} upsets")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("## Model Details")
    lines.append(f"- **Training Data**: Real historical NCAA tournament games (2008-2025, 1072 games)")
    lines.append(f"- **Models**: 5-model ensemble (LR + XGBoost + Vegas + Agent Swarm + Monte Carlo)")
    lines.append(f"- **LR 5-fold AUC**: ~0.696 (trained on real outcomes)")
    lines.append(f"- **XGB 5-fold AUC**: ~0.675 (trained on real outcomes)")
    lines.append(f"- **Upset targets**: R64=7, R32=3, S16=1, E8=1, F4=0, NCG=0")
    lines.append(f"- **1/2-seed protection**: Applied in R32+")
    lines.append(f"- **Built**: 2026-03-19")
    lines.append("")
    lines.append("*Generated by Memphis Labs March Madness ML Pipeline V5 (Historical Model)*")

    return '\n'.join(lines)


def build_flowing_bracket(results_df, team_lookup, lr, xgb_model, scaler):
    """Build a bracket that flows properly through each round.
    Uses R64 predictions from ensemble, then constructs matchups for each subsequent round."""
    from bracket_predictor import compute_delta_features, SHARED_FEATURES, get_hist_seed_win_rate
    import numpy as np

    # Get R64 results from ensemble
    r64_games = results_df[results_df['_round'] == 'R64'].copy()

    # Build probability lookup from ensemble
    prob_lookup = {}
    for _, row in results_df.iterrows():
        prob_lookup[(row['_team_a'], row['_team_b'])] = row['ensemble_prob_a']
        prob_lookup[(row['_team_b'], row['_team_a'])] = row['ensemble_prob_b']

    def get_prob(ta, tb):
        """Get win probability for ta over tb."""
        if (ta, tb) in prob_lookup:
            return prob_lookup[(ta, tb)]
        # Fall back to seed-based
        sa = team_lookup.get(ta, {}).get('seed', 8)
        sb = team_lookup.get(tb, {}).get('seed', 8)
        return get_hist_seed_win_rate(sa, sb)

    # Organize R64 by region and bracket position
    # Standard bracket order: (1,16), (8,9), (5,12), (4,13), (6,11), (3,14), (7,10), (2,15)
    regions_data = {}
    for _, row in r64_games.iterrows():
        region = row['_region']
        if region not in regions_data:
            regions_data[region] = []
        regions_data[region].append({
            'team_a': row['_team_a'],
            'team_b': row['_team_b'],
            'seed_a': int(row['_seed_a']),
            'seed_b': int(row['_seed_b']),
            'prob_a': float(row['ensemble_prob_a']),
            'region': region,
        })

    # Apply upset targets per round
    all_round_picks = {}

    # R64
    r64_picks = []
    for region, games in regions_data.items():
        for g in games:
            r64_picks.append({**g, 'round': 'R64'})

    r64_picks = apply_upset_targets(r64_picks, UPSET_TARGETS['R64'], 'R64')
    all_round_picks['R64'] = r64_picks

    # Build R32 matchups from R64 winners
    # Standard bracket pairing: winners of games 1&2, 3&4, 5&6, 7&8 in each region
    bracket_pairs = [(1, 16, 8, 9), (5, 12, 4, 13), (6, 11, 3, 14), (7, 10, 2, 15)]

    r32_picks = []
    for region in sorted(regions_data.keys()):
        region_r64 = [p for p in r64_picks if p['region'] == region]
        # Create a lookup by seed matchup
        r64_winners = {}
        for p in region_r64:
            pick = p['pick']
            pick_seed = p['seed_a'] if pick == p['team_a'] else p['seed_b']
            # Store by both seeds
            r64_winners[(p['seed_a'], p['seed_b'])] = (pick, pick_seed)

        # Pair up R32 matchups
        for sa1, sb1, sa2, sb2 in bracket_pairs:
            w1_info = r64_winners.get((sa1, sb1)) or r64_winners.get((sb1, sa1))
            w2_info = r64_winners.get((sa2, sb2)) or r64_winners.get((sb2, sa2))
            if w1_info and w2_info:
                w1, s1 = w1_info
                w2, s2 = w2_info
                prob_1 = get_prob(w1, w2)
                r32_picks.append({
                    'team_a': w1, 'team_b': w2,
                    'seed_a': s1, 'seed_b': s2,
                    'prob_a': prob_1,
                    'region': region, 'round': 'R32',
                })

    r32_picks = apply_upset_targets(r32_picks, UPSET_TARGETS['R32'], 'R32')
    all_round_picks['R32'] = r32_picks

    # Build S16 from R32 winners
    s16_picks = []
    for region in sorted(regions_data.keys()):
        region_r32 = [p for p in r32_picks if p['region'] == region]
        if len(region_r32) >= 4:
            # Pair games 1&2, 3&4
            for i in range(0, len(region_r32), 2):
                if i + 1 < len(region_r32):
                    g1, g2 = region_r32[i], region_r32[i + 1]
                    w1 = g1['pick']
                    s1 = g1['seed_a'] if w1 == g1['team_a'] else g1['seed_b']
                    w2 = g2['pick']
                    s2 = g2['seed_a'] if w2 == g2['team_a'] else g2['seed_b']
                    prob_1 = get_prob(w1, w2)
                    s16_picks.append({
                        'team_a': w1, 'team_b': w2,
                        'seed_a': s1, 'seed_b': s2,
                        'prob_a': prob_1,
                        'region': region, 'round': 'S16',
                    })

    s16_picks = apply_upset_targets(s16_picks, UPSET_TARGETS['S16'], 'S16')
    all_round_picks['S16'] = s16_picks

    # Build E8 from S16 winners
    e8_picks = []
    for region in sorted(regions_data.keys()):
        region_s16 = [p for p in s16_picks if p['region'] == region]
        if len(region_s16) >= 2:
            g1, g2 = region_s16[0], region_s16[1]
            w1 = g1['pick']
            s1 = g1['seed_a'] if w1 == g1['team_a'] else g1['seed_b']
            w2 = g2['pick']
            s2 = g2['seed_a'] if w2 == g2['team_a'] else g2['seed_b']
            prob_1 = get_prob(w1, w2)
            e8_picks.append({
                'team_a': w1, 'team_b': w2,
                'seed_a': s1, 'seed_b': s2,
                'prob_a': prob_1,
                'region': region, 'round': 'E8',
            })

    e8_picks = apply_upset_targets(e8_picks, UPSET_TARGETS['E8'], 'E8')
    all_round_picks['E8'] = e8_picks

    # Build F4 from E8 winners
    e8_winners = []
    for p in e8_picks:
        w = p['pick']
        s = p['seed_a'] if w == p['team_a'] else p['seed_b']
        e8_winners.append((w, s, p['region']))

    f4_picks = []
    if len(e8_winners) >= 4:
        # Pair: regions 1&2, regions 3&4 (alphabetical)
        for i in range(0, len(e8_winners), 2):
            if i + 1 < len(e8_winners):
                w1, s1, r1 = e8_winners[i]
                w2, s2, r2 = e8_winners[i + 1]
                prob_1 = get_prob(w1, w2)
                f4_picks.append({
                    'team_a': w1, 'team_b': w2,
                    'seed_a': s1, 'seed_b': s2,
                    'prob_a': prob_1,
                    'region': 'Final Four', 'round': 'F4',
                })

    f4_picks = apply_upset_targets(f4_picks, UPSET_TARGETS['F4'], 'F4')
    all_round_picks['F4'] = f4_picks

    # Build NCG from F4 winners
    f4_winners = []
    for p in f4_picks:
        w = p['pick']
        s = p['seed_a'] if w == p['team_a'] else p['seed_b']
        f4_winners.append((w, s))

    ncg_picks = []
    if len(f4_winners) >= 2:
        w1, s1 = f4_winners[0]
        w2, s2 = f4_winners[1]
        prob_1 = get_prob(w1, w2)
        ncg_picks.append({
            'team_a': w1, 'team_b': w2,
            'seed_a': s1, 'seed_b': s2,
            'prob_a': prob_1,
            'region': 'Championship', 'round': 'NCG',
        })

    ncg_picks = apply_upset_targets(ncg_picks, UPSET_TARGETS['NCG'], 'NCG')
    all_round_picks['NCG'] = ncg_picks

    return all_round_picks


def apply_upset_targets(picks, n_upset_target, rnd):
    """Apply upset target logic to a round's picks."""
    for p in picks:
        # Determine favorite/underdog
        if p['seed_a'] < p['seed_b']:
            p['fav_team'] = p['team_a']
            p['und_team'] = p['team_b']
            p['fav_seed'] = p['seed_a']
            p['und_seed'] = p['seed_b']
            p['upset_prob'] = 1 - p['prob_a']
        elif p['seed_a'] > p['seed_b']:
            p['fav_team'] = p['team_b']
            p['und_team'] = p['team_a']
            p['fav_seed'] = p['seed_b']
            p['und_seed'] = p['seed_a']
            p['upset_prob'] = p['prob_a']
        else:
            p['fav_team'] = p['team_a']
            p['und_team'] = p['team_b']
            p['fav_seed'] = p['seed_a']
            p['und_seed'] = p['seed_b']
            p['upset_prob'] = 1 - p['prob_a']

        # Default pick by probability
        p['default_pick'] = p['team_a'] if p['prob_a'] >= 0.5 else p['team_b']
        default_seed = p['seed_a'] if p['default_pick'] == p['team_a'] else p['seed_b']
        p['is_default_upset'] = (default_seed > p['fav_seed']) and (p['fav_seed'] != p['und_seed'])

    # Count existing upsets
    existing_upsets = [p for p in picks if p['is_default_upset']]
    n_existing = len(existing_upsets)

    games_to_upset = set()
    games_to_revert = set()

    if n_existing < n_upset_target:
        needed = n_upset_target - n_existing
        candidates = [
            p for p in picks
            if not p['is_default_upset']
            and p['fav_seed'] != p['und_seed']
            and p['upset_prob'] > 0.20
        ]
        if rnd == 'R32':
            candidates = [c for c in candidates if c['fav_seed'] not in PROTECTED_SEEDS_R32]
        elif rnd == 'S16':
            candidates = [c for c in candidates if c['fav_seed'] not in PROTECTED_SEEDS_S16]
        elif rnd in ('E8', 'F4', 'NCG'):
            candidates = [c for c in candidates if c['fav_seed'] not in PROTECTED_SEEDS_LATE]
        candidates.sort(key=lambda x: x['upset_prob'], reverse=True)
        for i, c in enumerate(candidates):
            if i >= needed: break
            games_to_upset.add((c['team_a'], c['team_b']))

    elif n_existing > n_upset_target:
        excess = n_existing - n_upset_target
        revert_candidates = sorted(existing_upsets, key=lambda x: x['upset_prob'])
        for i, c in enumerate(revert_candidates):
            if i >= excess: break
            games_to_revert.add((c['team_a'], c['team_b']))

    # Apply picks
    for p in picks:
        key = (p['team_a'], p['team_b'])
        if key in games_to_upset:
            p['pick'] = p['und_team']
        elif key in games_to_revert:
            p['pick'] = p['fav_team']
        else:
            p['pick'] = p['default_pick']

        pick_seed = p['seed_a'] if p['pick'] == p['team_a'] else p['seed_b']
        p['is_upset'] = (pick_seed > p['fav_seed']) and (p['fav_seed'] != p['und_seed'])

    return picks


def main():
    print("=" * 60)
    print("  HISTORICAL MODEL BRACKET GENERATOR")
    print("=" * 60)

    # Phase 1: Pull data
    tables, sb = pull_supabase_data()

    # Phase 2: Load real historical data + train
    hist_df = load_historical_data()
    matchups_df, team_lookup, mc_lookup = build_2026_features(tables)

    if matchups_df.empty:
        print("ERROR: No matchups found.")
        return

    # Phase 3: Train on real data
    lr, xgb_model, scaler = train_models(hist_df)

    # Phase 4: Predict ensemble on all matchups
    results_df = predict_ensemble(matchups_df, lr, xgb_model, scaler)

    # Phase 5: Build flowing bracket with upset targets
    print("\n" + "=" * 60)
    print("BUILDING FLOWING BRACKET WITH UPSET TARGETS")
    print("=" * 60)
    all_picks = build_flowing_bracket(results_df, team_lookup, lr, xgb_model, scaler)

    # Print upset selections
    for rnd in ['R64', 'R32', 'S16', 'E8', 'F4', 'NCG']:
        round_picks = all_picks.get(rnd, [])
        upsets = [p for p in round_picks if p.get('is_upset', False)]
        if upsets:
            print(f"\n  {rnd} Upsets ({len(upsets)}):")
            for p in upsets:
                pick = p['pick']
                pick_seed = p['seed_a'] if pick == p['team_a'] else p['seed_b']
                loser = p['team_b'] if pick == p['team_a'] else p['team_a']
                loser_seed = p['seed_b'] if pick == p['team_a'] else p['seed_a']
                print(f"    ({pick_seed}) {pick} over ({loser_seed}) {loser}")

    # Print bracket path
    print("\n  BRACKET PATH:")
    for rnd in ['R64', 'R32', 'S16', 'E8', 'F4', 'NCG']:
        round_picks = all_picks.get(rnd, [])
        if round_picks:
            print(f"\n  {rnd}:")
            for p in round_picks:
                pick_seed = p['seed_a'] if p['pick'] == p['team_a'] else p['seed_b']
                upset_mark = " *UPSET*" if p.get('is_upset') else ""
                print(f"    ({p['seed_a']}) {p['team_a']} vs ({p['seed_b']}) {p['team_b']} -> ({pick_seed}) {p['pick']}{upset_mark}")

    # Phase 6: Generate markdown
    md = format_bracket_md(all_picks)
    out_path = '/home/chase/march-madness-ml/HISTORICAL_MODEL_BRACKET.md'
    with open(out_path, 'w') as f:
        f.write(md)
    print(f"\n  Bracket saved to {out_path}")

    print("\n" + "=" * 60)
    print("  HISTORICAL MODEL BRACKET COMPLETE!")
    print("=" * 60)


if __name__ == '__main__':
    main()
