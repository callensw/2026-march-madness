#!/usr/bin/env python3
"""
March Madness 2026 ML Bracket Predictor — V5
5-model ensemble: LR, XGBoost, Vegas, Agent Swarm V2, Monte Carlo

V5: Complete rebuild with enriched data
  - 9 new features (conference_strength, coaching, eFG%, FT rate, OREB%, close games, variance)
  - Vegas implied probability as Model 3 (30% weight — strongest signal)
  - V2 agent swarm data (8 agents with diverse reasoning)
  - Fixed scales (three_pt_pct decimal, turnover_rate per-possession, experience continuous)
  - Historical seed ceilings + round-based seed regression retained from V4
"""

import os, sys, re, json, warnings
import numpy as np
import pandas as pd
from collections import Counter
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import brier_score_loss, roc_auc_score
import xgboost as xgb
from supabase import create_client

warnings.filterwarnings('ignore')
np.random.seed(42)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SUPABASE_URL = "https://kakjbyoxqjvwnsdbqcnb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtha2pieW94cWp2d25zZGJxY25iIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTQ3NDEyOCwiZXhwIjoyMDg1MDUwMTI4fQ.sDeyE82yzMUC7wq9MFIVY2SU2paZP8ofogAe1RndRlE"

N_SIMULATIONS = 10_000

# V5 Ensemble weights
W_LR = 0.15
W_XGB = 0.25
W_VEGAS = 0.30    # THE anchor — most accurate public signal
W_AGENT = 0.20    # V2 agent swarm
W_MC = 0.10       # Tournament context prior

# Breaking news adjustments
BREAKING_NEWS = {'Louisville': -0.03, 'Alabama': -0.02, 'Duke': -0.01}

# Historical seed win rates
HIST_SEED_WIN_RATE = {
    (1, 16): 0.991, (2, 15): 0.938, (3, 14): 0.857, (4, 13): 0.800,
    (5, 12): 0.649, (6, 11): 0.627, (7, 10): 0.608, (8, 9): 0.512,
}

# Seed-conditioned distributions for synthetic data
AEM_BY_SEED = {
    1: (28.5, 3.5), 2: (24.0, 3.5), 3: (21.5, 3.5), 4: (19.0, 4.0),
    5: (16.5, 4.0), 6: (14.5, 4.5), 7: (12.5, 4.5), 8: (10.5, 4.5),
    9: (9.5, 4.5), 10: (8.0, 5.0), 11: (7.0, 5.5), 12: (4.5, 5.0),
    13: (2.0, 4.5), 14: (0.0, 4.0), 15: (-3.0, 4.0), 16: (-7.0, 5.0),
}
KENPOM_RANK_BY_SEED = {
    1: (4, 3), 2: (12, 5), 3: (18, 6), 4: (24, 8), 5: (30, 10), 6: (35, 12),
    7: (40, 14), 8: (45, 15), 9: (50, 15), 10: (55, 18), 11: (55, 20), 12: (65, 22),
    13: (80, 25), 14: (100, 30), 15: (130, 35), 16: (160, 40),
}
EXPECTED_KENPOM = {s: v[0] for s, v in KENPOM_RANK_BY_SEED.items()}

# V5: Conference strength by seed tier (for synthetic data)
CONF_STRENGTH_BY_SEED = {
    1: (5.0, 1.0), 2: (4.8, 1.0), 3: (4.5, 1.2), 4: (4.2, 1.2),
    5: (4.0, 1.5), 6: (3.8, 1.5), 7: (3.5, 1.5), 8: (3.5, 1.8),
    9: (3.0, 1.8), 10: (2.8, 1.8), 11: (2.5, 1.5), 12: (1.8, 1.0),
    13: (1.2, 0.5), 14: (0.8, 0.3), 15: (0.6, 0.2), 16: (0.5, 0.2),
}
# Coach tournament apps by seed
COACH_APPS_BY_SEED = {
    1: (12, 8), 2: (10, 7), 3: (8, 6), 4: (8, 7), 5: (6, 5), 6: (6, 6),
    7: (5, 5), 8: (4, 4), 9: (4, 4), 10: (3, 3), 11: (3, 3), 12: (2, 2),
    13: (1, 1), 14: (1, 1), 15: (1, 1), 16: (1, 1),
}

# Historical seed ceilings
CEILING_F4 = {
    1: 1.00, 2: 0.40, 3: 0.25, 4: 0.18, 5: 0.12, 6: 0.10, 7: 0.08, 8: 0.05,
    9: 0.04, 10: 0.06, 11: 0.07, 12: 0.05, 13: 0.02, 14: 0.01, 15: 0.005, 16: 0.002,
}
CEILING_CHAMP = {
    1: 0.50, 2: 0.20, 3: 0.12, 4: 0.08, 5: 0.05, 6: 0.04, 7: 0.03, 8: 0.02,
    9: 0.015, 10: 0.025, 11: 0.03, 12: 0.02, 13: 0.008, 14: 0.004, 15: 0.002, 16: 0.001,
}
CEILING_WINNER = {
    1: 0.25, 2: 0.10, 3: 0.06, 4: 0.04, 5: 0.025, 6: 0.02, 7: 0.015, 8: 0.01,
    9: 0.008, 10: 0.012, 11: 0.015, 12: 0.01, 13: 0.004, 14: 0.002, 15: 0.001, 16: 0.0005,
}

# Seed regression for later rounds
SEED_REGRESSION_WEIGHT = {1: 0.0, 2: 0.10, 3: 0.20, 4: 0.25, 5: 0.30, 6: 0.35}

ROUND_MAP = {
    'R64': 1, 'Round of 64': 1, 'First Round': 1,
    'R32': 2, 'Round of 32': 2, 'Second Round': 2,
    'S16': 3, 'Sweet 16': 3, 'Sweet Sixteen': 3,
    'E8': 4, 'Elite 8': 4, 'Elite Eight': 4,
    'F4': 5, 'Final Four': 5, 'Final 4': 5,
    'NCG': 6, 'Championship': 6, 'National Championship': 6,
}

# V5: Expanded feature set (available in both historical + 2026)
SHARED_FEATURES = [
    # Core KenPom deltas
    'seed_delta', 'kenpom_rank_delta', 'adj_efficiency_margin_delta',
    'adj_o_delta', 'adj_d_delta', 'tempo_delta',
    # Shooting & ball control
    'three_pt_pct_delta', 'efg_pct_delta', 'turnover_rate_delta',
    # New advanced deltas
    'ft_rate_delta', 'oreb_pct_delta', 'conference_strength_delta',
    'coach_apps_delta', 'close_game_wpct_delta', 'variance_delta',
    # Roster
    'experience_score_delta', 'draft_prospects_delta',
    # Form
    'win_pct_delta', 'last_10_win_pct_delta',
    # Context
    'seed_a_val', 'seed_b_val', 'higher_seed_kenpom', 'aem_sum',
    'tempo_avg', 'hist_seed_win_rate', 'round_num', 'seed_kenpom_gap_delta',
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def parse_record(rec):
    if not rec or not isinstance(rec, str): return 0.5
    parts = rec.split('-')
    if len(parts) == 2:
        try:
            w, l = int(parts[0]), int(parts[1])
            return w / (w + l) if (w + l) > 0 else 0.5
        except ValueError: return 0.5
    return 0.5

def parse_streak(streak):
    if not streak or not isinstance(streak, str): return 0
    try:
        if streak.startswith('W'): return int(streak[1:])
        elif streak.startswith('L'): return -int(streak[1:])
    except (ValueError, IndexError): return 0
    return 0

def get_hist_seed_win_rate(sa, sb):
    key = (min(sa, sb), max(sa, sb))
    if key in HIST_SEED_WIN_RATE:
        rate = HIST_SEED_WIN_RATE[key]
        return rate if sa <= sb else 1 - rate
    return expit(0.08 * (sb - sa))

def moneyline_to_prob(ml):
    """Convert American moneyline to implied probability."""
    if ml is None: return None
    ml = float(ml)
    if ml < 0: return abs(ml) / (abs(ml) + 100)
    else: return 100 / (ml + 100)


# ─────────────────────────────────────────────
# PHASE 1: DATA EXTRACTION
# ─────────────────────────────────────────────
def pull_supabase_data():
    print("=" * 60)
    print("PHASE 1: DATA EXTRACTION")
    print("=" * 60)
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    tables = {}
    for table in ['mm_teams', 'mm_players', 'mm_games', 'mm_agent_votes', 'mm_monte_carlo']:
        resp = sb.table(table).select('*').execute()
        tables[table] = pd.DataFrame(resp.data)
        print(f"  {table}: {len(tables[table])} rows")
    return tables, sb


def aggregate_player_features(players_df, teams_df):
    if players_df.empty: return teams_df
    team_col = 'name' if 'name' in teams_df.columns else 'team_name'
    team_agg = players_df.groupby('team_name').agg(
        top_scorer_ppg=('points_per_game', 'max'),
        injured_count=('is_injured', 'sum'),
        draft_prospects=('nba_draft_prospect', 'sum'),
    ).reset_index()
    starters = players_df[players_df['is_starter'] == True]
    if not starters.empty:
        sa = starters.groupby('team_name')['assists_per_game'].sum().reset_index()
        sa.columns = ['team_name', 'total_starter_assists']
        team_agg = team_agg.merge(sa, on='team_name', how='left')
    else:
        team_agg['total_starter_assists'] = 0
    team_agg['total_starter_assists'] = team_agg['total_starter_assists'].fillna(0)
    teams_df = teams_df.merge(team_agg, left_on=team_col, right_on='team_name', how='left', suffixes=('', '_player'))
    return teams_df


# ─────────────────────────────────────────────
# SYNTHETIC HISTORICAL DATA (V5: expanded features)
# ─────────────────────────────────────────────
def generate_synthetic_team(seed):
    aem_mean, aem_std = AEM_BY_SEED[seed]
    kp_mean, kp_std = KENPOM_RANK_BY_SEED[seed]
    cs_mean, cs_std = CONF_STRENGTH_BY_SEED[seed]
    ca_mean, ca_std = COACH_APPS_BY_SEED[seed]

    aem = np.random.normal(aem_mean, aem_std)
    adj_o = np.random.normal(112 + aem * 0.4, 3)
    adj_d = adj_o - aem
    kenpom_rank = max(1, int(np.random.normal(kp_mean, kp_std)))
    tempo = np.random.normal(68, 4)
    three_pt_pct = np.random.normal(0.345, 0.025)
    turnover_rate = np.random.normal(0.16, 0.025)
    experience = np.random.normal(5.5 + seed * 0.1, 1.0)  # V5: realistic range 3.5-8.0
    wins = max(10, min(35, int(np.random.normal(30 - seed, 4))))
    losses = max(2, min(20, int(np.random.normal(2 + seed * 0.8, 3))))
    last_10_wins = max(3, min(10, int(np.random.normal(8 - seed * 0.2, 1.5))))
    draft_prospects = max(0, int(np.random.normal(max(0, 3 - seed * 0.2), 1)))

    # V5 new features
    efg_pct = np.random.normal(0.52 + aem * 0.001, 0.02)
    ft_rate = np.random.normal(0.34, 0.05)
    oreb_pct = np.random.normal(30.0, 3.5)
    conf_strength = max(0.3, np.random.normal(cs_mean, cs_std))
    coach_apps = max(1, int(np.random.normal(ca_mean, ca_std)))
    close_game_wpct = np.random.normal(0.55 - seed * 0.01, 0.15)
    close_game_wpct = np.clip(close_game_wpct, 0.1, 0.9)
    variance = np.random.normal(11.0 + seed * 0.2, 2.0)

    return {
        'seed': seed, 'kenpom_rank': kenpom_rank,
        'adj_o': adj_o, 'adj_d': adj_d, 'adj_efficiency_margin': aem,
        'adj_tempo': tempo, 'three_pt_pct': three_pt_pct, 'efg_pct': efg_pct,
        'turnover_rate': turnover_rate, 'ft_rate': ft_rate, 'oreb_pct': oreb_pct,
        'experience_score': experience, 'conference_strength': conf_strength,
        'coach_tournament_apps': coach_apps, 'close_game_wpct': close_game_wpct,
        'performance_variance': variance,
        'win_pct': wins / (wins + losses), 'last_10_win_pct': last_10_wins / 10,
        'draft_prospects': draft_prospects,
    }


def compute_delta_features(ta, tb, round_num=1):
    sa, sb = ta['seed'], tb['seed']
    gap_a = EXPECTED_KENPOM.get(sa, 100) - ta['kenpom_rank']
    gap_b = EXPECTED_KENPOM.get(sb, 100) - tb['kenpom_rank']
    return {
        'seed_delta': sa - sb,
        'kenpom_rank_delta': ta['kenpom_rank'] - tb['kenpom_rank'],
        'adj_efficiency_margin_delta': ta['adj_efficiency_margin'] - tb['adj_efficiency_margin'],
        'adj_o_delta': ta['adj_o'] - tb['adj_o'],
        'adj_d_delta': ta['adj_d'] - tb['adj_d'],
        'tempo_delta': ta.get('adj_tempo', 68) - tb.get('adj_tempo', 68),
        'three_pt_pct_delta': ta['three_pt_pct'] - tb['three_pt_pct'],
        'efg_pct_delta': ta.get('efg_pct', 0.52) - tb.get('efg_pct', 0.52),
        'turnover_rate_delta': ta['turnover_rate'] - tb['turnover_rate'],
        'ft_rate_delta': ta.get('ft_rate', 0.34) - tb.get('ft_rate', 0.34),
        'oreb_pct_delta': ta.get('oreb_pct', 30.0) - tb.get('oreb_pct', 30.0),
        'conference_strength_delta': ta.get('conference_strength', 3.0) - tb.get('conference_strength', 3.0),
        'coach_apps_delta': ta.get('coach_tournament_apps', 5) - tb.get('coach_tournament_apps', 5),
        'close_game_wpct_delta': ta.get('close_game_wpct', 0.5) - tb.get('close_game_wpct', 0.5),
        'variance_delta': ta.get('performance_variance', 12.0) - tb.get('performance_variance', 12.0),
        'experience_score_delta': np.clip(ta['experience_score'] - tb['experience_score'], -1.5, 1.5),
        'draft_prospects_delta': ta.get('draft_prospects', 0) - tb.get('draft_prospects', 0),
        'win_pct_delta': ta['win_pct'] - tb['win_pct'],
        'last_10_win_pct_delta': ta['last_10_win_pct'] - tb['last_10_win_pct'],
        'seed_a_val': sa, 'seed_b_val': sb,
        'higher_seed_kenpom': min(ta['kenpom_rank'], tb['kenpom_rank']),
        'aem_sum': ta['adj_efficiency_margin'] + tb['adj_efficiency_margin'],
        'tempo_avg': (ta.get('adj_tempo', 68) + tb.get('adj_tempo', 68)) / 2,
        'hist_seed_win_rate': get_hist_seed_win_rate(sa, sb),
        'round_num': round_num,
        'seed_kenpom_gap_delta': gap_a - gap_b,
    }


def load_historical_data():
    """Load REAL historical tournament data (2008-2025, 1072 games).
    Falls back to synthetic generation if CSV not found."""
    csv_path = os.path.join(os.path.dirname(__file__), 'historical_tournament_data.csv')
    if os.path.exists(csv_path):
        print("\n  Loading REAL historical tournament data...")
        hist_df = pd.read_csv(csv_path)
        print(f"  Loaded {len(hist_df)} real tournament games from {hist_df['year'].nunique()} tournaments ({int(hist_df['year'].min())}-{int(hist_df['year'].max())})")
        print(f"  Upset rate: {((hist_df['seed_a_val'] < hist_df['seed_b_val']) & (hist_df['outcome'] == 0)).sum() + ((hist_df['seed_a_val'] > hist_df['seed_b_val']) & (hist_df['outcome'] == 1)).sum()}/{len(hist_df)} = {(((hist_df['seed_a_val'] < hist_df['seed_b_val']) & (hist_df['outcome'] == 0)).sum() + ((hist_df['seed_a_val'] > hist_df['seed_b_val']) & (hist_df['outcome'] == 1)).sum()) / len(hist_df):.1%}")
        # Verify all required features exist
        missing = [f for f in SHARED_FEATURES if f not in hist_df.columns]
        if missing:
            print(f"  WARNING: Missing features: {missing}")
        return hist_df
    else:
        print(f"\n  WARNING: Historical CSV not found at {csv_path}")
        print("  Falling back to synthetic data generation...")
        return generate_synthetic_historical_data()


def generate_synthetic_historical_data(n_tournaments=22):
    """Legacy synthetic data generation (fallback only)."""
    print("\n  Generating synthetic historical data (V5 expanded features)...")
    r64_matchups = [(1, 16), (8, 9), (5, 12), (4, 13), (2, 15), (7, 10), (3, 14), (6, 11)]
    rows = []
    for yr in range(n_tournaments):
        for region in range(4):
            teams = {s: generate_synthetic_team(s) for s in range(1, 17)}
            r64_winners = []
            for seed_a, seed_b in r64_matchups:
                ta_, tb_ = teams[seed_a], teams[seed_b]
                features = compute_delta_features(ta_, tb_, round_num=1)
                aem_diff = ta_['adj_efficiency_margin'] - tb_['adj_efficiency_margin']
                k = 0.035 + np.random.normal(0, 0.005)
                mom = 0.05 * (ta_['last_10_win_pct'] - tb_['last_10_win_pct'])
                exp_b = 0.01 * (ta_['experience_score'] - tb_['experience_score'])
                p_a = expit(k * aem_diff + mom + exp_b)
                outcome = 1 if np.random.random() < p_a else 0
                features['outcome'] = outcome
                rows.append(features)
                r64_winners.append(seed_a if outcome == 1 else seed_b)
            r32_winners = []
            for i in range(0, 8, 2):
                sa_, sb_ = r64_winners[i], r64_winners[i + 1]
                ta_, tb_ = teams[sa_], teams[sb_]
                features = compute_delta_features(ta_, tb_, round_num=2)
                aem_diff = ta_['adj_efficiency_margin'] - tb_['adj_efficiency_margin']
                p_a = expit(0.033 * aem_diff + 0.05 * (ta_['last_10_win_pct'] - tb_['last_10_win_pct']))
                features['outcome'] = 1 if np.random.random() < p_a else 0
                rows.append(features)
                r32_winners.append(sa_ if features['outcome'] == 1 else sb_)
            s16_winners = []
            for i in range(0, 4, 2):
                sa_, sb_ = r32_winners[i], r32_winners[i + 1]
                ta_, tb_ = teams[sa_], teams[sb_]
                features = compute_delta_features(ta_, tb_, round_num=3)
                p_a = expit(0.030 * (ta_['adj_efficiency_margin'] - tb_['adj_efficiency_margin']))
                features['outcome'] = 1 if np.random.random() < p_a else 0
                rows.append(features)
                s16_winners.append(sa_ if features['outcome'] == 1 else sb_)
            sa_, sb_ = s16_winners[0], s16_winners[1]
            ta_, tb_ = teams[sa_], teams[sb_]
            features = compute_delta_features(ta_, tb_, round_num=4)
            features['outcome'] = 1 if np.random.random() < expit(0.030 * (ta_['adj_efficiency_margin'] - tb_['adj_efficiency_margin'])) else 0
            rows.append(features)
    hist_df = pd.DataFrame(rows)
    print(f"  Generated {len(hist_df)} matchups with {len(SHARED_FEATURES)} features")
    return hist_df


# ─────────────────────────────────────────────
# PHASE 2: FEATURE ENGINEERING (2026 DATA)
# ─────────────────────────────────────────────
def build_2026_features(tables):
    print("\n" + "=" * 60)
    print("PHASE 2: FEATURE ENGINEERING (2026)")
    print("=" * 60)

    teams_df = tables['mm_teams'].copy()
    players_df = tables['mm_players'].copy()
    games_df = tables['mm_games'].copy()
    mc_df = tables['mm_monte_carlo'].copy()

    teams_df = aggregate_player_features(players_df, teams_df)

    # Build team lookup
    team_col = 'name' if 'name' in teams_df.columns else 'team_name'
    team_lookup = {}
    for _, row in teams_df.iterrows():
        name = row.get(team_col, '')
        seed = int(row.get('seed', 16)) if pd.notna(row.get('seed')) else 16
        adj_o = float(row.get('adj_o', 100)) if pd.notna(row.get('adj_o')) else 100.0
        adj_d = float(row.get('adj_d', 100)) if pd.notna(row.get('adj_d')) else 100.0

        # Parse close game record
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
            'top_scorer_ppg': float(row.get('top_scorer_ppg', 15)) if pd.notna(row.get('top_scorer_ppg')) else 15.0,
            'current_streak': parse_streak(row.get('current_streak', 'W0')),
        }

    # MC lookup
    mc_lookup = {}
    for _, row in mc_df.iterrows():
        name = row.get('team_name', '')
        mc_lookup[name] = {
            'prob_s16': float(row.get('prob_s16', 0)) if pd.notna(row.get('prob_s16')) else 0,
            'prob_e8': float(row.get('prob_e8', 0)) if pd.notna(row.get('prob_e8')) else 0,
            'prob_f4': float(row.get('prob_f4', 0)) if pd.notna(row.get('prob_f4')) else 0,
            'prob_winner': float(row.get('prob_winner', 0)) if pd.notna(row.get('prob_winner')) else 0,
        }

    # Deduplicate games — take most recent per (team_a, team_b, round) and drop old rounds
    # Only use R64 and R32 games that have been freshly analyzed
    games_df = games_df.sort_values('analyzed_at', ascending=False, na_position='last')
    games_df = games_df.drop_duplicates(subset=['team_a', 'team_b', 'round'], keep='first')
    # Only keep rounds that have been run through the V2 agent swarm
    games_df = games_df[games_df['round'].isin(['R64', 'R32', 'S16', 'E8', 'F4', 'NCG'])]
    print(f"  After dedup: {len(games_df)} unique games")

    # Build features for each game
    matchup_features = []
    for _, game in games_df.iterrows():
        team_a, team_b = game.get('team_a', ''), game.get('team_b', '')
        round_str = game.get('round', 'R64')
        region = game.get('region', '')
        round_num = ROUND_MAP.get(round_str, 1)

        ta = team_lookup.get(team_a)
        tb = team_lookup.get(team_b)
        if ta is None or tb is None:
            continue

        features = compute_delta_features(ta, tb, round_num)

        # Agent swarm features (V2 agents)
        vote_a = float(game.get('vote_count_a', 0) or 0)
        vote_b = float(game.get('vote_count_b', 0) or 0)
        total_votes = vote_a + vote_b
        features['agent_consensus_a'] = vote_a / total_votes if total_votes > 0 else 0.5
        features['agent_win_prob_a'] = float(game.get('team_a_win_prob', 0.5) or 0.5)
        features['agent_uncertainty'] = float(game.get('combined_uncertainty', 0.3) or 0.3)

        # Vegas features (V5 NEW)
        ml_a = game.get('vegas_moneyline_a')
        ml_b = game.get('vegas_moneyline_b')
        spread = game.get('vegas_spread')
        vegas_prob_a = None
        if ml_a is not None and ml_b is not None:
            p_a = moneyline_to_prob(ml_a)
            p_b = moneyline_to_prob(ml_b)
            if p_a is not None and p_b is not None:
                total = p_a + p_b
                vegas_prob_a = p_a / total  # remove vig
        elif spread is not None:
            vegas_prob_a = expit(-float(spread) * 0.035)  # spread to prob approximation
        features['vegas_prob_a'] = vegas_prob_a if vegas_prob_a is not None else np.nan
        features['_has_vegas'] = vegas_prob_a is not None

        # Monte Carlo features
        mc_a = mc_lookup.get(team_a, {})
        mc_b = mc_lookup.get(team_b, {})
        features['mc_s16_prob_delta'] = mc_a.get('prob_s16', 0) - mc_b.get('prob_s16', 0)
        features['mc_e8_prob_delta'] = mc_a.get('prob_e8', 0) - mc_b.get('prob_e8', 0)
        features['mc_winner_prob_delta'] = mc_a.get('prob_winner', 0) - mc_b.get('prob_winner', 0)

        # Metadata
        features['_team_a'] = team_a
        features['_team_b'] = team_b
        features['_round'] = round_str
        features['_region'] = region
        features['_seed_a'] = ta['seed']
        features['_seed_b'] = tb['seed']

        matchup_features.append(features)

    matchups_df = pd.DataFrame(matchup_features)
    print(f"  Built features for {len(matchups_df)} matchups")
    print(f"  Vegas coverage: {(matchups_df['vegas_prob_a'] != 0.5).sum()} games with lines")
    return matchups_df, team_lookup, mc_lookup


# ─────────────────────────────────────────────
# PHASE 3: MODEL TRAINING
# ─────────────────────────────────────────────
def train_models(hist_df):
    print("\n" + "=" * 60)
    print("PHASE 3: MODEL TRAINING (V5)")
    print("=" * 60)

    X = hist_df[SHARED_FEATURES].values
    y = hist_df['outcome'].values
    print(f"  Training on {len(X)} samples, {len(SHARED_FEATURES)} features")

    # Model 1: Calibrated Logistic Regression
    print("\n  --- Model 1: Logistic Regression (C=0.1, calibrated) ---")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    base_lr = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
    lr = CalibratedClassifierCV(base_lr, method='sigmoid', cv=5)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    auc = cross_val_score(base_lr, X_scaled, y, cv=cv, scoring='roc_auc')
    print(f"  5-Fold AUC: {auc.mean():.4f} (+/- {auc.std():.4f})")
    lr.fit(X_scaled, y)
    lr_range = lr.predict_proba(X_scaled)[:, 1]
    print(f"  Output range: [{lr_range.min():.3f}, {lr_range.max():.3f}]")

    # Model 2: XGBoost
    print("\n  --- Model 2: XGBoost ---")
    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric='logloss', use_label_encoder=False,
    )
    auc_xgb = cross_val_score(xgb_model, X, y, cv=cv, scoring='roc_auc')
    print(f"  5-Fold AUC: {auc_xgb.mean():.4f} (+/- {auc_xgb.std():.4f})")
    xgb_model.fit(X, y)

    print("\n  Top features:")
    imp = xgb_model.feature_importances_
    for i in np.argsort(imp)[::-1][:8]:
        print(f"    {SHARED_FEATURES[i]:35s} {imp[i]:.4f}")

    return lr, xgb_model, scaler


# ─────────────────────────────────────────────
# MODELS 3-5: VEGAS, AGENT SWARM, MONTE CARLO
# ─────────────────────────────────────────────
def vegas_prob(row):
    """Model 3: Vegas implied probability (no training — just math)."""
    v = row.get('vegas_prob_a', np.nan)
    if pd.isna(v): return 0.5  # Will be skipped by has_vegas flag
    return np.clip(v, 0.02, 0.98)

def agent_swarm_prob(row):
    """Model 4: V2 agent swarm consensus."""
    consensus = row.get('agent_consensus_a', 0.5)
    win_prob = row.get('agent_win_prob_a', 0.5)
    uncertainty = row.get('agent_uncertainty', 0.3)
    raw = 0.35 * consensus + 0.50 * win_prob + 0.15 * (1 - uncertainty)
    calibrated = 0.5 + (raw - 0.5) * (1 - uncertainty * 0.5)
    return np.clip(calibrated, 0.02, 0.98)

def monte_carlo_prob(row):
    """Model 5: Monte Carlo tournament prior."""
    s16_d = row.get('mc_s16_prob_delta', 0)
    e8_d = row.get('mc_e8_prob_delta', 0)
    winner_d = row.get('mc_winner_prob_delta', 0)
    combined = 0.50 * s16_d + 0.30 * e8_d + 0.20 * winner_d
    return np.clip(expit(5 * combined), 0.02, 0.98)


# ─────────────────────────────────────────────
# PHASE 4: META-ENSEMBLE
# ─────────────────────────────────────────────
def predict_ensemble(matchups_df, lr, xgb_model, scaler):
    print("\n" + "=" * 60)
    print("PHASE 4: META-ENSEMBLE (V5)")
    print("=" * 60)

    X_shared = matchups_df[SHARED_FEATURES].values
    X_scaled = scaler.transform(X_shared)

    lr_probs = lr.predict_proba(X_scaled)[:, 1]
    xgb_probs = xgb_model.predict_proba(X_shared)[:, 1]
    vegas_probs = matchups_df.apply(vegas_prob, axis=1).values
    agent_probs = matchups_df.apply(agent_swarm_prob, axis=1).values
    mc_probs = matchups_df.apply(monte_carlo_prob, axis=1).values

    # Check Vegas coverage
    has_vegas = matchups_df['_has_vegas'].values if '_has_vegas' in matchups_df.columns else np.zeros(len(lr_probs), dtype=bool)
    print(f"  Vegas data available for {has_vegas.sum()}/{len(has_vegas)} games")

    # Ensemble — redistribute Vegas weight to other models when no Vegas data
    ensemble_a = np.zeros(len(lr_probs))
    for i in range(len(ensemble_a)):
        if has_vegas[i]:
            ensemble_a[i] = (W_LR * lr_probs[i] + W_XGB * xgb_probs[i] +
                             W_VEGAS * vegas_probs[i] + W_AGENT * agent_probs[i] +
                             W_MC * mc_probs[i])
        else:
            # No Vegas — redistribute to stat models
            w_lr_adj = W_LR + W_VEGAS * 0.4
            w_xgb_adj = W_XGB + W_VEGAS * 0.4
            w_agent_adj = W_AGENT + W_VEGAS * 0.1
            w_mc_adj = W_MC + W_VEGAS * 0.1
            ensemble_a[i] = (w_lr_adj * lr_probs[i] + w_xgb_adj * xgb_probs[i] +
                             w_agent_adj * agent_probs[i] + w_mc_adj * mc_probs[i])

    # Breaking news adjustments
    team_a_names = matchups_df['_team_a'].values
    team_b_names = matchups_df['_team_b'].values
    for i in range(len(ensemble_a)):
        adj = BREAKING_NEWS.get(team_a_names[i], 0) - BREAKING_NEWS.get(team_b_names[i], 0)
        if adj != 0:
            ensemble_a[i] += adj

    # Seed regression for later rounds
    for i in range(len(ensemble_a)):
        rn = int(matchups_df.iloc[i].get('round_num', 1))
        rw = SEED_REGRESSION_WEIGHT.get(rn, 0)
        if rw > 0:
            sa, sb = int(matchups_df.iloc[i]['seed_a_val']), int(matchups_df.iloc[i]['seed_b_val'])
            seed_prior = get_hist_seed_win_rate(sa, sb)
            ensemble_a[i] = (1 - rw) * ensemble_a[i] + rw * seed_prior

    # Replace any NaN with 0.5
    ensemble_a = np.nan_to_num(ensemble_a, nan=0.5)
    ensemble_a = np.clip(ensemble_a, 0.02, 0.98)
    ensemble_b = 1 - ensemble_a

    def get_tier(p):
        m = max(p, 1-p)
        if m > 0.75: return 'LOCK'
        elif m > 0.65: return 'STRONG'
        elif m > 0.55: return 'LEAN'
        else: return 'TOSS-UP'

    results = matchups_df[['_team_a', '_team_b', '_round', '_region', '_seed_a', '_seed_b']].copy()
    results['lr_prob_a'] = np.round(lr_probs, 4)
    results['xgb_prob_a'] = np.round(xgb_probs, 4)
    results['vegas_prob_a'] = np.round(vegas_probs, 4)
    results['agent_prob_a'] = np.round(agent_probs, 4)
    results['mc_prob_a'] = np.round(mc_probs, 4)
    results['ensemble_prob_a'] = np.round(ensemble_a, 4)
    results['ensemble_prob_b'] = np.round(ensemble_b, 4)
    results['pick'] = results.apply(
        lambda r: r['_team_a'] if r['ensemble_prob_a'] >= 0.5 else r['_team_b'], axis=1)
    results['pick_confidence'] = np.round(np.maximum(ensemble_a, ensemble_b), 4)
    results['confidence_tier'] = results['pick_confidence'].apply(get_tier)

    # Print by round
    for rn in ['R64', 'R32', 'S16', 'E8', 'F4', 'NCG']:
        rg = results[results['_round'] == rn]
        if len(rg) == 0: continue
        print(f"\n  {'─'*55}")
        print(f"  {rn} ({len(rg)} games)")
        print(f"  {'─'*55}")
        for _, g in rg.iterrows():
            marker = {'LOCK': '***', 'STRONG': '**', 'LEAN': '*'}.get(g['confidence_tier'], '')
            print(f"  ({g['_seed_a']}) {g['_team_a']:20s} vs ({g['_seed_b']}) {g['_team_b']:20s} "
                  f"-> {g['pick']:20s} [{g['confidence_tier']:7s}] "
                  f"({g['ensemble_prob_a']:.1%}/{g['ensemble_prob_b']:.1%}) "
                  f"V={g['vegas_prob_a']:.0%} A={g['agent_prob_a']:.0%} {marker}")

    tier_counts = results['confidence_tier'].value_counts()
    print(f"\n  Tiers: {dict(tier_counts)}")
    return results


# ─────────────────────────────────────────────
# PHASE 5: BRACKET SIMULATION
# ─────────────────────────────────────────────
def run_bracket_simulation(results_df, team_lookup, n_sims=N_SIMULATIONS):
    print("\n" + "=" * 60)
    print(f"PHASE 5: BRACKET SIMULATION ({n_sims:,} sims)")
    print("=" * 60)

    prob_lookup = {}
    for _, row in results_df.iterrows():
        prob_lookup[(row['_team_a'], row['_team_b'])] = row['ensemble_prob_a']
        prob_lookup[(row['_team_b'], row['_team_a'])] = row['ensemble_prob_b']

    def gwp(ta, tb):
        if (ta, tb) in prob_lookup: return prob_lookup[(ta, tb)]
        a, b = team_lookup.get(ta, {}), team_lookup.get(tb, {})
        return expit(0.035 * (a.get('adj_efficiency_margin', 0) - b.get('adj_efficiency_margin', 0)))

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
    for _ in range(n_sims):
        rw_map = {}
        for rn, rt in regions.items():
            w64 = [rt.get(a) if np.random.random() < gwp(rt.get(a,''), rt.get(b,'')) else rt.get(b) for a, b in pairs]
            w32 = []
            for i in range(0, 8, 2):
                w = w64[i] if np.random.random() < gwp(w64[i], w64[i+1]) else w64[i+1]
                w32.append(w); adv[w]['S16'] += 1
            w16 = []
            for i in range(0, 4, 2):
                w = w32[i] if np.random.random() < gwp(w32[i], w32[i+1]) else w32[i+1]
                w16.append(w); adv[w]['E8'] += 1
            rw = w16[0] if np.random.random() < gwp(w16[0], w16[1]) else w16[1]
            adv[rw]['F4'] += 1; rw_map[rn] = rw

        rw = list(rw_map.values())
        if len(rw) >= 4:
            f1 = rw[0] if np.random.random() < gwp(rw[0], rw[1]) else rw[1]
            f2 = rw[2] if np.random.random() < gwp(rw[2], rw[3]) else rw[3]
            adv[f1]['Champ'] += 1; adv[f2]['Champ'] += 1
            ch = f1 if np.random.random() < gwp(f1, f2) else f2
            adv[ch]['Win'] += 1

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

    print("\n  TOP 15 CHAMPIONSHIP CONTENDERS:")
    print(f"  {'Team':25s} {'Seed':>4s} {'S16':>7s} {'E8':>7s} {'F4':>7s} {'Champ':>7s} {'Win':>7s}")
    print(f"  {'-'*65}")
    for _, t in sim_df.head(15).iterrows():
        print(f"  {t['team']:25s} {t['seed']:4d} {t['prob_s16']:7.1%} {t['prob_e8']:7.1%} "
              f"{t['prob_f4']:7.1%} {t['prob_championship']:7.1%} {t['prob_winner']:7.1%}")

    f4 = sim_df.nlargest(4, 'prob_f4')
    print(f"\n  MOST LIKELY FINAL FOUR:")
    for _, t in f4.iterrows():
        print(f"    ({t['seed']}) {t['team']} — {t['prob_f4']:.1%}")

    ch = sim_df.iloc[0]
    print(f"\n  PREDICTED CHAMPION: ({ch['seed']}) {ch['team']} — {ch['prob_winner']:.1%}")
    return sim_df


# ─────────────────────────────────────────────
# PHASE 6: WRITE TO SUPABASE
# ─────────────────────────────────────────────
def write_to_supabase(sb, results_df, sim_df):
    print("\n" + "=" * 60)
    print("PHASE 6: WRITE RESULTS TO SUPABASE")
    print("=" * 60)

    for tbl in ['mm_ml_predictions', 'mm_ml_simulations']:
        try: sb.table(tbl).delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
        except: pass

    def safe_float(v):
        f = float(v)
        return 0.5 if np.isnan(f) else f

    pred = []
    for _, r in results_df.iterrows():
        pred.append({
            'team_a': r['_team_a'], 'team_b': r['_team_b'],
            'round': r['_round'], 'region': r['_region'],
            'seed_a': int(r['_seed_a']), 'seed_b': int(r['_seed_b']),
            'lr_prob_a': safe_float(r['lr_prob_a']), 'xgb_prob_a': safe_float(r['xgb_prob_a']),
            'agent_prob_a': safe_float(r['agent_prob_a']), 'mc_prob_a': safe_float(r['mc_prob_a']),
            'ensemble_prob_a': safe_float(r['ensemble_prob_a']),
            'ensemble_prob_b': safe_float(r['ensemble_prob_b']),
            'pick': r['pick'], 'pick_confidence': safe_float(r['pick_confidence']),
            'confidence_tier': r['confidence_tier'],
        })
    for i in range(0, len(pred), 50):
        sb.table('mm_ml_predictions').insert(pred[i:i+50]).execute()
    print(f"  Inserted {len(pred)} predictions")

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
    print(f"  Inserted {len(sims)} simulations")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("\n" + "=" * 60)
    print("  MARCH MADNESS 2026 — ML BRACKET PREDICTOR V5")
    print("  5-Model Ensemble: LR + XGB + Vegas + Agent Swarm V2 + MC")
    print("  28 features | Enriched data | Historical ceilings")
    print("=" * 60)

    tables, sb = pull_supabase_data()
    hist_df = load_historical_data()
    matchups_df, team_lookup, mc_lookup = build_2026_features(tables)

    if matchups_df.empty:
        print("\nERROR: No matchups found.")
        return

    lr, xgb_model, scaler = train_models(hist_df)
    results_df = predict_ensemble(matchups_df, lr, xgb_model, scaler)
    sim_df = run_bracket_simulation(results_df, team_lookup)
    write_to_supabase(sb, results_df, sim_df)

    print("\n" + "=" * 60)
    print("  V5 COMPLETE!")
    print("=" * 60)


if __name__ == '__main__':
    main()
