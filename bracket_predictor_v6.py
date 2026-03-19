#!/usr/bin/env python3
"""
March Madness 2026 ML Bracket Predictor — V6: The Chaos Framework
Extends V5 with:
  System 1: Upset Archetype Classifier (Random Forest)
  System 2: Variance-Aware Bracket Simulation (correlated team performance)
  System 3: Anti-Chalk Diagnostics + 3 bracket outputs (EV, Chaos, Chalk)
"""

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

# Import everything from V5
from bracket_predictor import (
    pull_supabase_data, aggregate_player_features, generate_historical_data,
    generate_synthetic_team, compute_delta_features, build_2026_features,
    train_models, predict_ensemble, write_to_supabase,
    get_hist_seed_win_rate, moneyline_to_prob, parse_record,
    SUPABASE_URL, SUPABASE_KEY, EXPECTED_KENPOM, N_SIMULATIONS,
    SHARED_FEATURES, HIST_SEED_WIN_RATE, ROUND_MAP,
    CEILING_F4, CEILING_CHAMP, CEILING_WINNER,
    AEM_BY_SEED, KENPOM_RANK_BY_SEED, CONF_STRENGTH_BY_SEED, COACH_APPS_BY_SEED,
)
from supabase import create_client

np.random.seed(42)

POWER_CONFERENCES = ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Big East']


# ═══════════════════════════════════════════════
# SYSTEM 1: UPSET ARCHETYPE CLASSIFIER
# ═══════════════════════════════════════════════

def compute_upset_features_from_teams(fav, dog, agent_uncertainty=0.15, vegas_fav_prob=0.65):
    """Compute upset-specific features from favorite and underdog team dicts."""
    return {
        'underdog_kenpom_value': EXPECTED_KENPOM.get(dog['seed'], 100) - dog['kenpom_rank'],
        'tempo_mismatch': abs(fav.get('adj_tempo', 68) - dog.get('adj_tempo', 68)),
        'underdog_exp_edge': dog.get('experience_score', 5.5) - fav.get('experience_score', 5.5),
        'underdog_adj_d': dog.get('adj_d', 95),
        'favorite_to_rate': fav.get('turnover_rate', 0.16),
        'underdog_momentum': dog.get('last_10_win_pct', 0.5) - fav.get('last_10_win_pct', 0.5),
        'underdog_close_game_edge': dog.get('close_game_wpct', 0.5) - fav.get('close_game_wpct', 0.5),
        'underdog_ft_edge': dog.get('ft_rate', 0.34) - fav.get('ft_rate', 0.34),
        'underdog_oreb_edge': dog.get('oreb_pct', 30) - fav.get('oreb_pct', 30),
        'underdog_variance': dog.get('performance_variance', 12),
        'favorite_variance': fav.get('performance_variance', 12),
        'seed_gap': abs(fav['seed'] - dog['seed']),
        'agent_uncertainty': agent_uncertainty,
        'vegas_underdog_prob': 1.0 - vegas_fav_prob,
    }

UPSET_FEATURES = [
    'underdog_kenpom_value', 'tempo_mismatch', 'underdog_exp_edge',
    'underdog_adj_d', 'favorite_to_rate', 'underdog_momentum',
    'underdog_close_game_edge', 'underdog_ft_edge', 'underdog_oreb_edge',
    'underdog_variance', 'favorite_variance', 'seed_gap',
    'agent_uncertainty', 'vegas_underdog_prob',
]


def generate_upset_training_data(n_tournaments=30):
    """Generate training data specifically for upset classification."""
    print("  Generating upset training data...")
    r64_matchups = [(1, 16), (8, 9), (5, 12), (4, 13), (2, 15), (7, 10), (3, 14), (6, 11)]
    rows = []
    for _ in range(n_tournaments):
        for _ in range(4):  # 4 regions
            teams = {s: generate_synthetic_team(s) for s in range(1, 17)}
            for sa, sb in r64_matchups:
                ta, tb = teams[sa], teams[sb]
                # Determine favorite/underdog
                fav, dog = (ta, tb) if sa < sb else (tb, ta)
                fav_seed, dog_seed = min(sa, sb), max(sa, sb)

                # Simulate outcome
                aem_diff = fav['adj_efficiency_margin'] - dog['adj_efficiency_margin']
                k = 0.035 + np.random.normal(0, 0.005)
                mom = 0.05 * (fav['last_10_win_pct'] - dog['last_10_win_pct'])
                p_fav = expit(k * aem_diff + mom)

                # Simulate Vegas line (noisy version of true prob)
                vegas_fav = np.clip(p_fav + np.random.normal(0, 0.05), 0.3, 0.98)

                outcome_fav_wins = 1 if np.random.random() < p_fav else 0
                is_upset = 1 - outcome_fav_wins  # upset = favorite lost

                features = compute_upset_features_from_teams(
                    fav, dog,
                    agent_uncertainty=np.random.uniform(0.08, 0.20),
                    vegas_fav_prob=vegas_fav,
                )
                features['is_upset'] = is_upset
                rows.append(features)

    df = pd.DataFrame(rows)
    upset_rate = df['is_upset'].mean()
    print(f"  Generated {len(df)} games, upset rate: {upset_rate:.1%}")
    return df


def train_upset_model(upset_df):
    """Train the upset archetype Random Forest classifier."""
    print("\n  --- Upset Archetype Classifier (Random Forest) ---")

    X = upset_df[UPSET_FEATURES].values
    y = upset_df['is_upset'].values

    model = RandomForestClassifier(
        n_estimators=200, max_depth=5, min_samples_leaf=15,
        class_weight='balanced', random_state=42,
    )

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc = cross_val_score(model, X, y, cv=cv, scoring='roc_auc')
    print(f"  5-Fold AUC: {auc.mean():.4f} (+/- {auc.std():.4f})")

    model.fit(X, y)

    # Feature importances
    print("  Top upset features:")
    imp = model.feature_importances_
    for i in np.argsort(imp)[::-1][:6]:
        print(f"    {UPSET_FEATURES[i]:30s} {imp[i]:.4f}")

    return model


def apply_upset_adjustments(results_df, upset_model, team_lookup):
    """Apply upset probability to soften overconfident chalk."""
    print("\n" + "=" * 60)
    print("SYSTEM 1: UPSET ARCHETYPE ADJUSTMENTS")
    print("=" * 60)

    upset_probs = []
    adjusted_ensemble = results_df['ensemble_prob_a'].values.copy()

    for idx, row in results_df.iterrows():
        sa, sb = int(row['_seed_a']), int(row['_seed_b'])
        ta = team_lookup.get(row['_team_a'], {})
        tb = team_lookup.get(row['_team_b'], {})

        if sa == sb:  # same seed, no favorite
            upset_probs.append(0.0)
            continue

        # Determine favorite/underdog
        if sa < sb:
            fav, dog = ta, tb
            ensemble_fav = row['ensemble_prob_a']
            is_a_favorite = True
        else:
            fav, dog = tb, ta
            ensemble_fav = row['ensemble_prob_b']
            is_a_favorite = False

        # Build upset features
        vegas_fav = row.get('vegas_prob_a', 0.5) if is_a_favorite else row.get('ensemble_prob_b', 0.5)
        if pd.isna(vegas_fav): vegas_fav = ensemble_fav

        uf = compute_upset_features_from_teams(
            fav, dog,
            agent_uncertainty=row.get('agent_uncertainty', 0.15) if not pd.isna(row.get('agent_uncertainty', 0.15)) else 0.15,
            vegas_fav_prob=vegas_fav,
        )
        X_upset = np.array([[uf[f] for f in UPSET_FEATURES]])
        up = upset_model.predict_proba(X_upset)[0, 1]
        upset_probs.append(round(up, 4))

        # Apply adjustment: soften overconfident chalk
        if up > 0.35 and ensemble_fav > 0.55:
            max_adj = (ensemble_fav - 0.50) * 0.5
            adj = max_adj * (up - 0.35) / 0.65
            if is_a_favorite:
                adjusted_ensemble[results_df.index.get_loc(idx)] -= adj
            else:
                adjusted_ensemble[results_df.index.get_loc(idx)] += adj

    results_df['upset_probability'] = upset_probs
    results_df['ensemble_prob_a'] = np.clip(adjusted_ensemble, 0.02, 0.98)
    results_df['ensemble_prob_b'] = 1 - results_df['ensemble_prob_a']
    results_df['pick'] = results_df.apply(
        lambda r: r['_team_a'] if r['ensemble_prob_a'] >= 0.5 else r['_team_b'], axis=1)

    # Print top upset candidates
    r64 = results_df[results_df['_round'] == 'R64'].copy()
    r64_sorted = r64.sort_values('upset_probability', ascending=False)
    print("\n  TOP 10 UPSET CANDIDATES (R64):")
    print(f"  {'Rank':>4s}  {'Game':40s} {'Up%':>5s} {'Ens':>6s} {'Adj':>6s}")
    print(f"  {'-'*65}")
    for i, (_, g) in enumerate(r64_sorted.head(10).iterrows()):
        fav_seed = min(g['_seed_a'], g['_seed_b'])
        dog_seed = max(g['_seed_a'], g['_seed_b'])
        fav = g['_team_a'] if g['_seed_a'] == fav_seed else g['_team_b']
        dog = g['_team_a'] if g['_seed_a'] == dog_seed else g['_team_b']
        ens_fav = g['ensemble_prob_a'] if g['_seed_a'] == fav_seed else g['ensemble_prob_b']
        print(f"  {i+1:4d}  ({fav_seed}) {fav:16s} vs ({dog_seed}) {dog:16s} "
              f"{g['upset_probability']:5.0%} {ens_fav:6.1%} {g['pick']}")

    return results_df


# ═══════════════════════════════════════════════
# SYSTEM 2: VARIANCE-AWARE BRACKET SIMULATION
# ═══════════════════════════════════════════════

def simulate_bracket_with_variance(results_df, team_lookup, n_sims=N_SIMULATIONS):
    print("\n" + "=" * 60)
    print(f"SYSTEM 2: VARIANCE-AWARE SIMULATION ({n_sims:,} sims)")
    print("=" * 60)

    # Build probability lookup from adjusted ensemble
    prob_lookup = {}
    for _, row in results_df.iterrows():
        prob_lookup[(row['_team_a'], row['_team_b'])] = row['ensemble_prob_a']
        prob_lookup[(row['_team_b'], row['_team_a'])] = row['ensemble_prob_b']

    def base_gwp(ta, tb):
        if (ta, tb) in prob_lookup: return prob_lookup[(ta, tb)]
        a, b = team_lookup.get(ta, {}), team_lookup.get(tb, {})
        return expit(0.035 * (a.get('adj_efficiency_margin', 0) - b.get('adj_efficiency_margin', 0)))

    # Build regions
    regions = {}
    for _, row in results_df[results_df['_round'] == 'R64'].iterrows():
        r = row['_region']
        if r not in regions: regions[r] = {}
        regions[r][row['_seed_a']] = row['_team_a']
        regions[r][row['_seed_b']] = row['_team_b']

    all_teams = set()
    for rt in regions.values(): all_teams.update(rt.values())
    adv = {t: {'S16': 0, 'E8': 0, 'F4': 0, 'Champ': 0, 'Win': 0} for t in all_teams}

    pairs = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]

    # Track simulation-level stats for diagnostics
    all_r64_upsets = []
    all_r32_upsets = []
    all_ones_in_f4 = []
    cinderella_s16 = 0  # sims with 10+ seed in S16
    all_ones_s16 = 0    # sims with all 4 one-seeds in S16
    zero_ones_f4 = 0
    all_brackets = []    # store full brackets for chaos/chalk extraction

    rng = np.random.RandomState(2026)  # separate RNG for variance sims
    for sim in range(n_sims):
        # Draw tournament performance modifier for each team
        team_mods = {}
        for team in all_teams:
            td = team_lookup.get(team, {})
            base_var = 0.018

            three_pt_vol = (td.get('three_pt_pct', 0.34) - 0.34) / 0.10
            youth = (8.0 - td.get('experience_score', 5.5)) / 8.0
            pv = (td.get('performance_variance', 12.0) - 10.0) / 10.0
            conf = td.get('conference', '')
            conf_jump = 0.15 if conf not in POWER_CONFERENCES else 0.0

            def_stab = max(0, (92.0 - td.get('adj_d', 95)) / 15.0)
            ball_ctrl = max(0, (0.16 - td.get('turnover_rate', 0.16)) / 0.08)
            ft_clutch = max(0, (td.get('ft_rate', 0.34) - 0.28) / 0.15)

            var_width = base_var * (
                1.0
                + 0.20 * three_pt_vol
                + 0.20 * youth
                + 0.15 * pv
                + conf_jump
                - 0.20 * def_stab
                - 0.15 * ball_ctrl
                - 0.10 * ft_clutch
            )
            var_width = max(0.025, min(0.09, var_width))
            team_mods[team] = rng.normal(0, var_width)

        def gwp_var(ta, tb):
            bp = base_gwp(ta, tb)
            mod = team_mods.get(ta, 0) - team_mods.get(tb, 0)
            return np.clip(bp + mod, 0.05, 0.95)

        def flip(p):
            return rng.random() < p

        sim_r64_upsets = 0
        sim_r32_upsets = 0
        ones_in_s16 = 0
        has_cinderella = False
        bracket = {'r64': {}, 'r32': {}, 's16': {}, 'e8': {}, 'f4': {}, 'ncg': {}}

        rw_map = {}
        for rn, rt in regions.items():
            # R64
            w64 = []
            for sa, sb in pairs:
                ta, tb = rt.get(sa), rt.get(sb)
                if ta and tb:
                    w = ta if flip(gwp_var(ta, tb)) else tb
                    winner_seed = sa if w == ta else sb
                    if winner_seed > min(sa, sb) and abs(sa - sb) > 1:
                        sim_r64_upsets += 1
                else:
                    w = ta or tb
                    winner_seed = sa if w == ta else sb
                w64.append((w, winner_seed))
                bracket['r64'][(rn, sa, sb)] = (w, winner_seed)

            # R32
            w32 = []
            for i in range(0, 8, 2):
                ta, sa_ = w64[i]
                tb, sb_ = w64[i+1]
                w = ta if flip(gwp_var(ta, tb)) else tb
                ws = sa_ if w == ta else sb_
                if ws > min(sa_, sb_) and abs(sa_ - sb_) > 1:
                    sim_r32_upsets += 1
                w32.append((w, ws))
                adv[w]['S16'] += 1
                if ws == 1: ones_in_s16 += 1
                if ws >= 10: has_cinderella = True
                bracket['r32'][(rn, i//2)] = (w, ws)

            # S16
            w16 = []
            for i in range(0, 4, 2):
                ta, sa_ = w32[i]
                tb, sb_ = w32[i+1]
                w = ta if flip(gwp_var(ta, tb)) else tb
                ws = sa_ if w == ta else sb_
                w16.append((w, ws))
                adv[w]['E8'] += 1
                bracket['s16'][(rn, i//2)] = (w, ws)

            # E8
            ta, sa_ = w16[0]
            tb, sb_ = w16[1]
            rw = ta if flip(gwp_var(ta, tb)) else tb
            rw_seed = sa_ if rw == ta else sb_
            adv[rw]['F4'] += 1
            rw_map[rn] = (rw, rw_seed)
            bracket['e8'][rn] = (rw, rw_seed)

        # F4
        rw_list = list(rw_map.values())
        ones_f4 = sum(1 for _, s in rw_list if s == 1)
        all_ones_in_f4.append(ones_f4)
        if ones_f4 == 0: zero_ones_f4 += 1

        if len(rw_list) >= 4:
            ta, sa_ = rw_list[0]; tb, sb_ = rw_list[1]
            f1 = ta if flip(gwp_var(ta, tb)) else tb
            f1s = sa_ if f1 == ta else sb_
            ta, sa_ = rw_list[2]; tb, sb_ = rw_list[3]
            f2 = ta if flip(gwp_var(ta, tb)) else tb
            f2s = sa_ if f2 == ta else sb_
            adv[f1]['Champ'] += 1; adv[f2]['Champ'] += 1
            ch = f1 if flip(gwp_var(f1, f2)) else f2
            chs = f1s if ch == f1 else f2s
            adv[ch]['Win'] += 1
            bracket['f4'] = {'semi1': (f1, f1s), 'semi2': (f2, f2s)}
            bracket['ncg'] = {'champion': (ch, chs), 'runner_up': (f2 if ch == f1 else f1, f2s if ch == f1 else f1s)}
        bracket['r64_upsets'] = sim_r64_upsets
        bracket['r32_upsets'] = sim_r32_upsets

        all_r64_upsets.append(sim_r64_upsets)
        all_r32_upsets.append(sim_r32_upsets)
        if has_cinderella: cinderella_s16 += 1
        if ones_in_s16 == 4: all_ones_s16 += 1
        all_brackets.append(bracket)

    # Build simulation results
    sim_results = []
    for team, counts in adv.items():
        td = team_lookup.get(team, {})
        seed = td.get('seed', 16)
        sim_results.append({
            'team': team, 'seed': seed,
            'region': next((r for r, ts in regions.items() if team in ts.values()), ''),
            'prob_s16': round(min(counts['S16'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_e8': round(min(counts['E8'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_f4': round(min(counts['F4'] / n_sims, CEILING_F4.get(seed, 1.0)), 4),
            'prob_championship': round(min(counts['Champ'] / n_sims, CEILING_CHAMP.get(seed, 1.0)), 4),
            'prob_winner': round(min(counts['Win'] / n_sims, CEILING_WINNER.get(seed, 1.0)), 4),
        })
    sim_df = pd.DataFrame(sim_results).sort_values('prob_winner', ascending=False)

    # Print results
    print("\n  TOP 20 CHAMPIONSHIP CONTENDERS (Variance-Aware):")
    print(f"  {'Team':25s} {'Seed':>4s} {'S16':>7s} {'E8':>7s} {'F4':>7s} {'Champ':>7s} {'Win':>7s}")
    print(f"  {'-'*65}")
    for _, t in sim_df.head(20).iterrows():
        print(f"  {t['team']:25s} {t['seed']:4d} {t['prob_s16']:7.1%} {t['prob_e8']:7.1%} "
              f"{t['prob_f4']:7.1%} {t['prob_championship']:7.1%} {t['prob_winner']:7.1%}")

    f4 = sim_df.nlargest(4, 'prob_f4')
    print(f"\n  MOST LIKELY FINAL FOUR:")
    for _, t in f4.iterrows():
        print(f"    ({t['seed']}) {t['team']} — {t['prob_f4']:.1%}")

    ch = sim_df.iloc[0]
    print(f"\n  PREDICTED CHAMPION: ({ch['seed']}) {ch['team']} — {ch['prob_winner']:.1%}")

    # ═══ SYSTEM 3: ANTI-CHALK DIAGNOSTICS ═══
    print("\n" + "=" * 60)
    print("SYSTEM 3: ANTI-CHALK DIAGNOSTICS")
    print("=" * 60)

    mean_r64 = np.mean(all_r64_upsets)
    std_r64 = np.std(all_r64_upsets)
    mean_r32 = np.mean(all_r32_upsets)
    pct_all_ones_s16 = all_ones_s16 / n_sims
    pct_cind = cinderella_s16 / n_sims
    mean_ones_f4 = np.mean(all_ones_in_f4)
    pct_zero_ones = zero_ones_f4 / n_sims

    print(f"  Avg R64 upsets per sim:           {mean_r64:.1f}  (target: 6.0-7.0)")
    print(f"  Std dev R64 upsets:               {std_r64:.1f}  (target: 2.0-3.0)")
    print(f"  Avg R32 upsets per sim:           {mean_r32:.1f}  (target: 2.5-3.5)")
    print(f"  % sims all 4 one-seeds S16:      {pct_all_ones_s16:.1%}  (target: 30-40%)")
    print(f"  % sims with 10+ seed in S16:     {pct_cind:.1%}  (target: 70-80%)")
    print(f"  Avg one-seeds in F4:              {mean_ones_f4:.1f}  (target: 1.3-1.8)")
    print(f"  % sims 0 one-seeds in F4:        {pct_zero_ones:.1%}  (target: 8-15%)")

    warnings = []
    if mean_r64 < 5.0: warnings.append("TOO CHALKY: Increase base_var")
    if mean_r64 > 9.0: warnings.append("TOO CHAOTIC: Decrease base_var")
    if mean_ones_f4 > 2.5: warnings.append("F4 TOO CHALKY: 1-seeds too dominant")
    if pct_cind < 0.50: warnings.append("NOT ENOUGH CINDERELLAS")
    for w in warnings:
        print(f"  ⚠️  {w}")
    if not warnings:
        print(f"  ✓ All diagnostics in range!")

    # Find realistic bracket: sim closest to 6-7 R64 upsets (prefer 7)
    target_upsets = 7
    best_realistic_idx = min(range(len(all_r64_upsets)),
                             key=lambda i: abs(all_r64_upsets[i] - target_upsets))
    # Among sims with exactly target_upsets, pick one with a 1-seed champion
    candidates = [i for i, u in enumerate(all_r64_upsets) if u == target_upsets]
    if not candidates:
        candidates = [i for i, u in enumerate(all_r64_upsets) if abs(u - target_upsets) <= 1]
    # Prefer a bracket where at least 2 one-seeds make F4
    for c in candidates:
        b = all_brackets[c]
        ones_in = sum(1 for v in b.get('e8', {}).values() if v[1] == 1)
        if ones_in >= 2:
            best_realistic_idx = c
            break

    chaos_idx = np.argmax(all_r64_upsets)
    chalk_idx = np.argmin(all_r64_upsets)

    realistic = all_brackets[best_realistic_idx]
    chaos = all_brackets[chaos_idx]
    chalk = all_brackets[chalk_idx]

    print(f"\n  REALISTIC BRACKET (sim #{best_realistic_idx}): {all_r64_upsets[best_realistic_idx]} R64 upsets, "
          f"champion = {realistic.get('ncg', {}).get('champion', ('?',))[0]}")
    print(f"  CHAOS BRACKET (sim #{chaos_idx}): {all_r64_upsets[chaos_idx]} R64 upsets, "
          f"champion = {chaos.get('ncg', {}).get('champion', ('?',))[0]}")
    print(f"  CHALK BRACKET (sim #{chalk_idx}): {all_r64_upsets[chalk_idx]} R64 upsets, "
          f"champion = {chalk.get('ncg', {}).get('champion', ('?',))[0]}")

    return sim_df, all_brackets, regions, best_realistic_idx, chaos_idx, chalk_idx


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  MARCH MADNESS 2026 — V6: THE CHAOS FRAMEWORK")
    print("  V5 Ensemble + Upset Classifier + Variance Sims + Diagnostics")
    print("=" * 60)

    # ── V5 Pipeline ──
    tables, sb = pull_supabase_data()
    hist_df = generate_historical_data(n_tournaments=22)
    matchups_df, team_lookup, mc_lookup = build_2026_features(tables)

    if matchups_df.empty:
        print("\nERROR: No matchups found.")
        return

    lr, xgb_model, scaler = train_models(hist_df)
    results_df = predict_ensemble(matchups_df, lr, xgb_model, scaler)

    # Save V5 results for comparison
    v5_r64 = results_df[results_df['_round'] == 'R64'][['_team_a', '_team_b', '_seed_a', '_seed_b', 'ensemble_prob_a', 'pick']].copy()

    # ── System 1: Upset Classifier ──
    print("\n" + "=" * 60)
    print("TRAINING UPSET ARCHETYPE CLASSIFIER")
    print("=" * 60)
    upset_df = generate_upset_training_data(n_tournaments=30)
    upset_model = train_upset_model(upset_df)
    results_df = apply_upset_adjustments(results_df, upset_model, team_lookup)

    # ── System 2: Variance-Aware Simulation ──
    sim_df, all_brackets, regions, realistic_idx, chaos_idx, chalk_idx = \
        simulate_bracket_with_variance(results_df, team_lookup)

    pairs = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]

    def print_sim_bracket(bracket, title):
        """Print a full bracket from a simulation run."""
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")

        print("\n  R64:")
        for rn in sorted(regions.keys()):
            for sa, sb in pairs:
                key = (rn, sa, sb)
                if key in bracket.get('r64', {}):
                    w, ws = bracket['r64'][key]
                    rt = regions[rn]
                    ta, tb = rt.get(sa, '?'), rt.get(sb, '?')
                    upset = " *** UPSET" if ws > min(sa, sb) and abs(sa-sb) > 1 else ""
                    print(f"    {rn:10s} ({sa}) {ta:20s} vs ({sb}) {tb:20s} -> ({ws}) {w}{upset}")

        for rnd_name, rnd_key in [('R32', 'r32'), ('S16', 's16')]:
            if rnd_key in bracket and bracket[rnd_key]:
                print(f"\n  {rnd_name}:")
                for (rn, gi), (w, ws) in sorted(bracket[rnd_key].items()):
                    print(f"    {rn:10s} ({ws}) {w}")

        if 'e8' in bracket and bracket['e8']:
            print(f"\n  E8 (Regional Champions):")
            for rn, (w, ws) in sorted(bracket['e8'].items()):
                print(f"    {rn:10s} ({ws}) {w}")

        if 'f4' in bracket and bracket.get('f4'):
            f4 = bracket['f4']
            print(f"\n  F4: ({f4['semi1'][1]}) {f4['semi1'][0]}  |  ({f4['semi2'][1]}) {f4['semi2'][0]}")

        if 'ncg' in bracket and bracket.get('ncg'):
            ncg = bracket['ncg']
            ch = ncg.get('champion', ('?', 0))
            ru = ncg.get('runner_up', ('?', 0))
            print(f"\n  🏆 CHAMPION: ({ch[1]}) {ch[0]}")
            print(f"  Runner-up: ({ru[1]}) {ru[0]}")

    # ── Print all three sim-based brackets ──
    realistic = all_brackets[realistic_idx]
    print_sim_bracket(realistic, f"REALISTIC BRACKET (sim #{realistic_idx}, {realistic['r64_upsets']} R64 upsets)")

    chaos = all_brackets[chaos_idx]
    print_sim_bracket(chaos, f"CHAOS BRACKET (sim #{chaos_idx}, {chaos['r64_upsets']} R64 upsets)")

    chalk = all_brackets[chalk_idx]
    print_sim_bracket(chalk, f"CHALK BRACKET (sim #{chalk_idx}, {chalk['r64_upsets']} R64 upsets)")

    # ── Smart Upset Bracket (flip top 6-7 by upset probability) ──
    print(f"\n{'='*60}")
    print(f"  SMART UPSET BRACKET (top 7 upsets flipped by model)")
    print(f"{'='*60}")

    r64_games = results_df[results_df['_round'] == 'R64'].copy()
    # Only consider games where the favorite is the current pick (not already an upset pick)
    # and seed gap > 1 (exclude 8v9)
    r64_games['seed_gap'] = abs(r64_games['_seed_a'] - r64_games['_seed_b'])
    upset_candidates = r64_games[
        (r64_games['seed_gap'] > 1) &
        (r64_games['upset_probability'] > 0.40)
    ].sort_values('upset_probability', ascending=False)

    n_flips = min(7, len(upset_candidates))
    flipped = upset_candidates.head(n_flips)

    print(f"\n  Flipping {n_flips} picks:")
    smart_picks = results_df.copy()
    for idx, row in flipped.iterrows():
        # Flip the pick to the underdog
        fav_seed = min(row['_seed_a'], row['_seed_b'])
        dog = row['_team_b'] if row['_seed_a'] == fav_seed else row['_team_a']
        dog_seed = max(row['_seed_a'], row['_seed_b'])
        fav = row['_team_a'] if row['_seed_a'] == fav_seed else row['_team_b']
        print(f"    ({dog_seed}) {dog:20s} over ({fav_seed}) {fav:20s} (UP={row['upset_probability']:.0%})")
        smart_picks.loc[idx, 'pick'] = dog

    print(f"\n  Smart Upset R64:")
    for _, g in smart_picks[smart_picks['_round'] == 'R64'].iterrows():
        is_upset = g['pick'] != g['_team_a'] if g['_seed_a'] < g['_seed_b'] else g['pick'] != g['_team_b']
        tag = " *** UPSET" if is_upset and abs(g['_seed_a'] - g['_seed_b']) > 1 else ""
        print(f"    ({g['_seed_a']}) {g['_team_a']:20s} vs ({g['_seed_b']}) {g['_team_b']:20s} -> {g['pick']}{tag}")

    # ── Write realistic bracket to Supabase as primary ──
    write_to_supabase(sb, results_df, sim_df)

    # ── Top 10 Championship Favorites ──
    print(f"\n{'='*60}")
    print(f"  TOP 10 CHAMPIONSHIP FAVORITES (Variance-Aware Sims)")
    print(f"{'='*60}")
    for i, (_, t) in enumerate(sim_df.head(10).iterrows(), 1):
        print(f"  {i:2d}. ({t['seed']}) {t['team']:25s} — {t['prob_winner']:.1%}")

    print(f"\n{'='*60}")
    print(f"  V6 COMPLETE!")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
