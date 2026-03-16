#!/usr/bin/env python3
"""
Monte Carlo Bracket Simulation for March Madness Agent Swarm.
Simulates 10,000 brackets using game-level win probabilities
produced by the multi-round debate system.

Zero API cost — pure numpy/random math.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
ROUND_ORDER = ["R64", "R32", "S16", "E8", "F4", "NCG"]

ROUND_DISPLAY = {
    "R64": "Round of 64",
    "R32": "Round of 32",
    "S16": "Sweet 16",
    "E8": "Elite 8",
    "F4": "Final Four",
    "NCG": "Championship",
}

# Historical upset rates by seed matchup (for estimating later-round games)
SEED_WIN_RATES = {
    (1, 16): 0.993, (2, 15): 0.938, (3, 14): 0.852, (4, 13): 0.791,
    (5, 12): 0.642, (6, 11): 0.625, (7, 10): 0.608, (8, 9): 0.514,
}


@dataclass
class TeamSim:
    name: str
    seed: int
    region: str
    kenpom_rank: int = 100


@dataclass
class GameProb:
    game_id: str
    team_a: TeamSim
    team_b: TeamSim
    team_a_win_prob: float
    round_name: str


@dataclass
class MonteCarloResult:
    """Results of a Monte Carlo bracket simulation."""
    n_simulations: int
    # team_name -> {round_name: probability}
    advancement_probs: dict[str, dict[str, float]]
    # team_name -> championship probability
    championship_probs: dict[str, float]
    # round_name -> expected upset count with CI
    upset_stats: dict[str, dict]
    # Top cinderella probabilities
    cinderella_stats: dict[str, float]
    # team metadata
    team_info: dict[str, TeamSim]


# ---------------------------------------------------------------------------
# Probability estimation for later rounds (when we don't have debate data)
# ---------------------------------------------------------------------------
def estimate_win_prob(team_a: TeamSim, team_b: TeamSim) -> float:
    """
    Estimate win probability from seed and KenPom rank when we don't have
    a debate-generated probability. Uses a logistic model based on
    KenPom rank differential.
    """
    # Seed-based base rate
    seeds = tuple(sorted([team_a.seed, team_b.seed]))
    if seeds in SEED_WIN_RATES:
        base_rate = SEED_WIN_RATES[seeds]
        # team_a is the higher seed (lower number)?
        if team_a.seed < team_b.seed:
            seed_prob = base_rate
        elif team_a.seed > team_b.seed:
            seed_prob = 1.0 - base_rate
        else:
            seed_prob = 0.5
    else:
        seed_prob = 0.5

    # KenPom rank differential adjustment
    rank_diff = team_b.kenpom_rank - team_a.kenpom_rank  # positive = team_a better
    # Logistic adjustment: ~0.02 per rank difference, capped
    kenpom_adj = max(-0.20, min(0.20, rank_diff * 0.003))

    # Blend seed-based and kenpom-adjusted
    combined = 0.6 * seed_prob + 0.4 * (0.5 + kenpom_adj)
    return max(0.02, min(0.98, combined))


# ---------------------------------------------------------------------------
# Single bracket simulation
# ---------------------------------------------------------------------------
def _simulate_one_bracket(
    r64_games: list[GameProb],
    rng: random.Random,
) -> dict[str, str]:
    """
    Simulate one complete bracket. Returns dict mapping round_name to
    list of (team_name,) for teams that reached that round.

    Returns: {team_name: furthest_round_reached}
    """
    team_progress: dict[str, str] = {}  # team -> furthest round

    # R64: use provided probabilities
    r64_winners = []
    for game in r64_games:
        # Record that both teams reached R64
        team_progress[game.team_a.name] = "R64"
        team_progress[game.team_b.name] = "R64"

        if rng.random() < game.team_a_win_prob:
            r64_winners.append(game.team_a)
        else:
            r64_winners.append(game.team_b)

    # Mark R64 winners as reaching R32
    for w in r64_winners:
        team_progress[w.name] = "R32"

    # Group winners by region for bracket progression
    by_region: dict[str, list[TeamSim]] = defaultdict(list)
    for w in r64_winners:
        by_region[w.region].append(w)

    # R32 through E8: within-region play
    current_round_idx = 1  # R32
    region_survivors: dict[str, list[TeamSim]] = dict(by_region)

    for round_idx in range(1, 4):  # R32, S16, E8
        round_name = ROUND_ORDER[round_idx]
        next_round = ROUND_ORDER[round_idx + 1]
        next_survivors: dict[str, list[TeamSim]] = {}

        for region, teams in region_survivors.items():
            winners = []
            for i in range(0, len(teams) - 1, 2):
                t1, t2 = teams[i], teams[i + 1]
                prob = estimate_win_prob(t1, t2)
                if rng.random() < prob:
                    winners.append(t1)
                else:
                    winners.append(t2)

            for w in winners:
                team_progress[w.name] = next_round

            next_survivors[region] = winners

        region_survivors = next_survivors

    # Final Four: East vs West, South vs Midwest
    f4_teams = []
    pairings = [("East", "West"), ("South", "Midwest")]
    for r1, r2 in pairings:
        t1_list = region_survivors.get(r1, [])
        t2_list = region_survivors.get(r2, [])
        if t1_list and t2_list:
            t1, t2 = t1_list[0], t2_list[0]
            prob = estimate_win_prob(t1, t2)
            if rng.random() < prob:
                winner = t1
            else:
                winner = t2
            team_progress[winner.name] = "NCG"
            f4_teams.append(winner)

    # Championship
    if len(f4_teams) == 2:
        t1, t2 = f4_teams[0], f4_teams[1]
        prob = estimate_win_prob(t1, t2)
        if rng.random() < prob:
            winner = t1
        else:
            winner = t2
        team_progress[winner.name] = "Winner"

    return team_progress


# ---------------------------------------------------------------------------
# Main simulation function
# ---------------------------------------------------------------------------
def simulate_bracket(
    r64_games: list[GameProb],
    n_sims: int = 10000,
    seed: int | None = None,
) -> MonteCarloResult:
    """
    Run n_sims bracket simulations using R64 game probabilities.
    Returns comprehensive probability tables.
    """
    rng = random.Random(seed)

    # Collect all teams
    all_teams: dict[str, TeamSim] = {}
    for game in r64_games:
        all_teams[game.team_a.name] = game.team_a
        all_teams[game.team_b.name] = game.team_b

    # Track advancement counts
    # advancement[team][round] = count of sims where team reached that round
    round_milestones = ["R32", "S16", "E8", "F4", "NCG", "Winner"]
    advancement: dict[str, dict[str, int]] = {
        name: {r: 0 for r in round_milestones}
        for name in all_teams
    }

    # Track upsets per round per simulation
    upset_counts: dict[str, list[int]] = {r: [] for r in ROUND_ORDER}

    for sim in range(n_sims):
        progress = _simulate_one_bracket(r64_games, rng)

        # Count R64 upsets (we can check directly)
        r64_upsets = 0
        for game in r64_games:
            higher_seed = game.team_a if game.team_a.seed < game.team_b.seed else game.team_b
            lower_seed = game.team_b if game.team_a.seed < game.team_b.seed else game.team_a
            if higher_seed.seed != lower_seed.seed:
                winner_round = progress.get(lower_seed.name, "R64")
                if winner_round != "R64":  # lower seed advanced = upset
                    r64_upsets += 1
        upset_counts["R64"].append(r64_upsets)

        # Record advancement
        for team_name, furthest_round in progress.items():
            for milestone in round_milestones:
                milestone_idx = round_milestones.index(milestone)
                furthest_idx = round_milestones.index(furthest_round) if furthest_round in round_milestones else -1
                if furthest_idx >= milestone_idx:
                    advancement[team_name][milestone] += 1

    # Convert counts to probabilities
    advancement_probs: dict[str, dict[str, float]] = {}
    for team_name, rounds in advancement.items():
        advancement_probs[team_name] = {
            r: count / n_sims for r, count in rounds.items()
        }

    # Championship probabilities
    championship_probs = {
        name: probs.get("Winner", 0.0)
        for name, probs in advancement_probs.items()
    }

    # Upset statistics
    upset_stats: dict[str, dict] = {}
    for round_name, counts in upset_counts.items():
        if counts:
            avg = sum(counts) / len(counts)
            sorted_counts = sorted(counts)
            ci_low = sorted_counts[int(0.025 * len(sorted_counts))]
            ci_high = sorted_counts[int(0.975 * len(sorted_counts))]
            upset_stats[round_name] = {
                "expected": round(avg, 1),
                "ci_low": ci_low,
                "ci_high": ci_high,
            }

    # Cinderella stats
    cinderella_stats = {}
    # P(any 12+ seed reaches S16)
    twelve_plus_s16 = 0
    for team_name, team in all_teams.items():
        if team.seed >= 12:
            prob_s16 = advancement_probs[team_name].get("S16", 0.0)
            if prob_s16 > 0.01:
                cinderella_stats[f"{team_name} (#{team.seed}) S16"] = prob_s16

    # P(any 9-16 seed reaches F4)
    nine_plus_f4 = 0
    for team_name, team in all_teams.items():
        if team.seed >= 9:
            prob_f4 = advancement_probs[team_name].get("F4", 0.0)
            nine_plus_f4 = 1.0 - (1.0 - nine_plus_f4) * (1.0 - prob_f4)

    cinderella_stats["Any 9-16 seed reaches F4"] = round(nine_plus_f4, 4)

    twelve_plus_s16_prob = 0.0
    for team_name, team in all_teams.items():
        if team.seed >= 12:
            prob_s16 = advancement_probs[team_name].get("S16", 0.0)
            twelve_plus_s16_prob = 1.0 - (1.0 - twelve_plus_s16_prob) * (1.0 - prob_s16)
    cinderella_stats["Any 12+ seed reaches S16"] = round(twelve_plus_s16_prob, 4)

    return MonteCarloResult(
        n_simulations=n_sims,
        advancement_probs=advancement_probs,
        championship_probs=championship_probs,
        upset_stats=upset_stats,
        cinderella_stats=cinderella_stats,
        team_info=all_teams,
    )


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------
def print_championship_table(result: MonteCarloResult, top_n: int = 10):
    """Print top championship contenders."""
    sorted_teams = sorted(
        result.championship_probs.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:top_n]

    print(f"\n{'='*60}")
    print(f"  TOP {top_n} CHAMPIONSHIP CONTENDERS ({result.n_simulations:,} simulations)")
    print(f"{'='*60}")
    print(f"  {'Team':<25} {'Seed':>4}  {'Champ%':>7}  {'F4%':>6}  {'E8%':>6}  {'S16%':>6}")
    print(f"  {'-'*55}")

    for team_name, champ_prob in sorted_teams:
        team = result.team_info[team_name]
        probs = result.advancement_probs[team_name]
        print(
            f"  {team_name:<25} #{team.seed:<3}  {champ_prob*100:>6.1f}%  "
            f"{probs.get('F4', 0)*100:>5.1f}%  {probs.get('E8', 0)*100:>5.1f}%  "
            f"{probs.get('S16', 0)*100:>5.1f}%"
        )


def print_full_advancement_table(result: MonteCarloResult):
    """Print every team's probability of reaching each round."""
    print(f"\n{'='*80}")
    print(f"  FULL ADVANCEMENT TABLE ({result.n_simulations:,} simulations)")
    print(f"{'='*80}")
    print(
        f"  {'Team':<25} {'Seed':>4}  {'R32%':>6}  {'S16%':>6}  "
        f"{'E8%':>6}  {'F4%':>6}  {'NCG%':>6}  {'Win%':>6}"
    )
    print(f"  {'-'*75}")

    # Sort by championship probability descending
    sorted_teams = sorted(
        result.advancement_probs.items(),
        key=lambda x: x[1].get("Winner", 0),
        reverse=True,
    )

    for team_name, probs in sorted_teams:
        team = result.team_info[team_name]
        print(
            f"  {team_name:<25} #{team.seed:<3}  {probs.get('R32', 0)*100:>5.1f}%  "
            f"{probs.get('S16', 0)*100:>5.1f}%  {probs.get('E8', 0)*100:>5.1f}%  "
            f"{probs.get('F4', 0)*100:>5.1f}%  {probs.get('NCG', 0)*100:>5.1f}%  "
            f"{probs.get('Winner', 0)*100:>5.1f}%"
        )


def print_upset_stats(result: MonteCarloResult):
    """Print expected upset counts per round."""
    print(f"\n{'='*60}")
    print(f"  EXPECTED UPSETS PER ROUND ({result.n_simulations:,} simulations)")
    print(f"{'='*60}")

    for round_name in ROUND_ORDER:
        stats = result.upset_stats.get(round_name)
        if stats:
            print(
                f"  {ROUND_DISPLAY.get(round_name, round_name)}: "
                f"{stats['expected']:.1f} upsets "
                f"(95% CI: {stats['ci_low']}-{stats['ci_high']})"
            )


def print_cinderella_stats(result: MonteCarloResult):
    """Print Cinderella probability stats."""
    print(f"\n{'='*60}")
    print(f"  CINDERELLA WATCH ({result.n_simulations:,} simulations)")
    print(f"{'='*60}")

    for label, prob in sorted(result.cinderella_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {label}: {prob*100:.1f}%")


def print_monte_carlo_report(result: MonteCarloResult):
    """Print the full Monte Carlo report."""
    print_championship_table(result)
    print_upset_stats(result)
    print_cinderella_stats(result)
    # Full table is very long — print only if verbose
    # print_full_advancement_table(result)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick test with synthetic data
    test_games = []
    teams_data = [
        ("Duke", 1, "East", 1), ("Siena", 16, "East", 192),
        ("Ohio State", 8, "East", 26), ("TCU", 9, "East", 43),
        ("St. John's", 5, "East", 16), ("Northern Iowa", 12, "East", 71),
        ("Kansas", 4, "East", 21), ("Cal Baptist", 13, "East", 106),
        ("Louisville", 6, "East", 19), ("USF", 11, "East", 49),
        ("Michigan State", 3, "East", 9), ("North Dakota State", 14, "East", 113),
        ("UCLA", 7, "East", 27), ("UCF", 10, "East", 54),
        ("UConn", 2, "East", 12), ("Furman", 15, "East", 190),
    ]

    teams = {name: TeamSim(name, seed, region, kenpom)
             for name, seed, region, kenpom in teams_data}

    matchups = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]
    probs = [0.99, 0.52, 0.64, 0.79, 0.62, 0.85, 0.61, 0.94]

    for (s1, s2), prob in zip(matchups, probs):
        t1 = [t for t in teams.values() if t.seed == s1 and t.region == "East"][0]
        t2 = [t for t in teams.values() if t.seed == s2 and t.region == "East"][0]
        test_games.append(GameProb(
            game_id=f"test_{s1}v{s2}",
            team_a=t1, team_b=t2,
            team_a_win_prob=prob,
            round_name="R64",
        ))

    result = simulate_bracket(test_games, n_sims=10000, seed=42)
    print_monte_carlo_report(result)
    print_full_advancement_table(result)

    # Verify probabilities sum correctly
    total_champ = sum(result.championship_probs.values())
    print(f"\nTotal championship probability: {total_champ:.4f} (should be ~1.0)")
