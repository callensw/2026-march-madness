#!/usr/bin/env python3
"""
Market Inefficiency Detection for March Madness Agent Swarm.

Compares swarm probabilities against implied Vegas odds to identify
games where the market is mispriced. Uses Kelly criterion for
position sizing and decomposes edge by agent contribution.

Zero additional API cost — post-processing on existing outputs.
"""

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from odds_tracker import (
    american_to_implied_prob,
    spread_to_implied_prob,
    find_game_odds,
    _team_match,
)

log = logging.getLogger("swarm")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class MarketEdge:
    """A single game's market inefficiency analysis."""
    game_id: str
    team_a: str
    team_b: str
    seed_a: int
    seed_b: int
    region: str
    round_name: str
    swarm_prob: float          # team_a win prob from swarm
    market_prob: float         # team_a implied prob from Vegas
    edge: float                # swarm_prob - market_prob (positive = swarm favors team_a more)
    combined_uncertainty: float
    agent_contributions: dict[str, float]   # agent_name -> agent's edge vs market
    contrarian_agents: list[tuple[str, float]]  # agents diverging >10% from market
    bet_side: str              # team name to bet on, or ""
    kelly_fraction: float      # Kelly criterion fraction (0 = no bet)
    recommendation: str        # human-readable recommendation
    vegas_spread: float | None = None
    vegas_moneyline: int | None = None


@dataclass
class MarketReport:
    """Full market inefficiency report across all games."""
    edges: list[MarketEdge]
    total_games: int
    games_with_odds: int
    inefficiencies: list[MarketEdge]   # |edge| > 0.05
    portfolio: list[dict]              # Kelly-sized positions


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------
def _get_market_prob_for_team_a(
    team_a: str, team_b: str, game_odds: dict
) -> tuple[float | None, float | None, int | None]:
    """
    Extract implied probability that team_a wins from Vegas odds.
    Returns (prob, spread, moneyline) — any can be None.
    """
    best_prob = None
    spread_val = None
    ml_val = None

    # Try spreads first (more accurate for close games)
    for team_key, spread_data in game_odds.get("spreads", {}).items():
        if _team_match(team_a, team_key):
            spread_val = spread_data["point"]
            best_prob = spread_to_implied_prob(spread_data["point"])
            break
        if _team_match(team_b, team_key):
            # team_b's spread — team_a prob is inverse
            spread_val = -spread_data["point"]
            best_prob = spread_to_implied_prob(-spread_data["point"])
            break

    # Try moneylines (use if no spread, or average with spread)
    ml_a = None
    ml_b = None
    for team_key, ml_data in game_odds.get("moneylines", {}).items():
        if _team_match(team_a, team_key):
            ml_a = ml_data["price"]
            ml_val = ml_a
        elif _team_match(team_b, team_key):
            ml_b = ml_data["price"]

    if ml_a is not None and ml_b is not None:
        # Remove vig: normalize both implied probs to sum to 1.0
        raw_a = american_to_implied_prob(ml_a)
        raw_b = american_to_implied_prob(ml_b)
        total = raw_a + raw_b
        if total > 0:
            no_vig_a = raw_a / total
            if best_prob is not None:
                # Average spread-implied and moneyline-implied
                best_prob = (best_prob + no_vig_a) / 2
            else:
                best_prob = no_vig_a
    elif ml_a is not None and best_prob is None:
        best_prob = american_to_implied_prob(ml_a)

    return best_prob, spread_val, ml_val


def analyze_game(
    game_id: str,
    team_a: str,
    team_b: str,
    seed_a: int,
    seed_b: int,
    region: str,
    round_name: str,
    swarm_prob: float,
    combined_uncertainty: float,
    agent_votes: list[dict],   # [{"agent_name": str, "win_probability": float}, ...]
    game_odds: dict,
) -> MarketEdge | None:
    """
    Compare swarm probability to market for a single game.
    Returns MarketEdge or None if odds unavailable.
    """
    market_prob, spread_val, ml_val = _get_market_prob_for_team_a(
        team_a, team_b, game_odds
    )
    if market_prob is None:
        return None

    edge = swarm_prob - market_prob

    # Decompose edge by agent
    agent_contributions = {}
    contrarian_agents = []
    for av in agent_votes:
        agent_edge = av["win_probability"] - market_prob
        agent_contributions[av["agent_name"]] = round(agent_edge, 4)
        if abs(agent_edge) > 0.10:
            contrarian_agents.append((av["agent_name"], round(agent_edge, 4)))

    # Sort contrarians by absolute divergence
    contrarian_agents.sort(key=lambda x: abs(x[1]), reverse=True)

    # Generate recommendation using Kelly criterion
    bet_side, kelly, recommendation = _generate_recommendation(
        edge, combined_uncertainty, swarm_prob, team_a, team_b,
        len(contrarian_agents), spread_val,
    )

    return MarketEdge(
        game_id=game_id,
        team_a=team_a,
        team_b=team_b,
        seed_a=seed_a,
        seed_b=seed_b,
        region=region,
        round_name=round_name,
        swarm_prob=swarm_prob,
        market_prob=market_prob,
        edge=edge,
        combined_uncertainty=combined_uncertainty,
        agent_contributions=agent_contributions,
        contrarian_agents=contrarian_agents,
        bet_side=bet_side,
        kelly_fraction=kelly,
        recommendation=recommendation,
        vegas_spread=spread_val,
        vegas_moneyline=ml_val,
    )


def _generate_recommendation(
    edge: float,
    uncertainty: float,
    swarm_prob: float,
    team_a: str,
    team_b: str,
    n_contrarian: int,
    spread: float | None,
) -> tuple[str, float, str]:
    """
    Generate bet recommendation using Kelly criterion with safety checks.
    Returns (bet_side, kelly_fraction, recommendation_text).
    """
    abs_edge = abs(edge)

    # Gate 1: minimum edge threshold
    if abs_edge < 0.05:
        return "", 0.0, "NO BET — market is efficient on this game"

    # Gate 2: edge must exceed 2x uncertainty
    if abs_edge < 2 * uncertainty:
        return "", 0.0, (
            f"NO BET — edge ({abs_edge:.1%}) exists but "
            f"uncertainty too high ({uncertainty:.1%})"
        )

    # Gate 3: require at least 2 agents supporting the contrarian view
    if n_contrarian < 2:
        return "", 0.0, (
            f"WATCH — edge ({abs_edge:.1%}) with only {n_contrarian} "
            f"contrarian agent(s); need broader agreement"
        )

    # Determine which side to bet
    if edge > 0:
        bet_side = team_a
        bet_prob = swarm_prob
    else:
        bet_side = team_b
        bet_prob = 1.0 - swarm_prob

    # Kelly criterion: f* = (bp - q) / b
    # where b = decimal odds - 1, p = our prob, q = 1 - p
    # Estimate decimal odds from market probability
    market_side_prob = 1.0 - bet_prob + abs_edge  # market's prob for the side we're betting
    if market_side_prob <= 0 or market_side_prob >= 1:
        return "", 0.0, "NO BET — edge calculation error"

    decimal_odds = 1.0 / market_side_prob  # fair odds from market
    b = decimal_odds - 1.0
    if b <= 0:
        return "", 0.0, "NO BET — negative implied odds"

    kelly = (b * bet_prob - (1.0 - bet_prob)) / b

    # Half-Kelly for safety
    kelly = max(0.0, kelly * 0.5)
    kelly = min(kelly, 0.10)  # never more than 10% of bankroll

    if kelly < 0.01:
        return "", 0.0, "NO BET — Kelly fraction too small"

    # Confidence label
    if abs_edge > 0.15:
        strength = "STRONG"
    elif abs_edge > 0.10:
        strength = "MODERATE"
    else:
        strength = "SMALL"

    spread_note = ""
    if spread is not None:
        # If betting underdog, note the spread
        if (edge > 0 and bet_side == team_a) or (edge < 0 and bet_side == team_b):
            spread_note = f" (spread: {spread:+.1f})"

    return bet_side, kelly, (
        f"BET {strength} — {kelly:.1%} Kelly on {bet_side}{spread_note} "
        f"(edge: {abs_edge:.1%}, uncertainty: {uncertainty:.1%})"
    )


# ---------------------------------------------------------------------------
# Full bracket analysis
# ---------------------------------------------------------------------------
def analyze_bracket(
    debates: list,    # list[GameDebate] from swarm_engine
    odds_data: list[dict],
    bankroll: float = 1000.0,
) -> MarketReport:
    """
    Run market analysis across all debated games.
    Returns a MarketReport with edges, inefficiencies, and portfolio.
    """
    edges: list[MarketEdge] = []
    games_with_odds = 0

    for debate in debates:
        if not debate.conductor:
            continue

        game = debate.game
        game_odds = find_game_odds(game.team_a, game.team_b, odds_data)
        if not game_odds:
            continue
        games_with_odds += 1

        # Collect agent vote probabilities (use Round 2 if available)
        final_votes = debate.round2_votes if debate.round2_votes else debate.votes
        agent_votes = [
            {"agent_name": v.agent_name, "win_probability": v.win_probability}
            for v in final_votes
            if not v.error and v.pick
        ]

        edge = analyze_game(
            game_id=game.id,
            team_a=game.team_a,
            team_b=game.team_b,
            seed_a=game.seed_a,
            seed_b=game.seed_b,
            region=game.region,
            round_name=game.round_name,
            swarm_prob=debate.conductor.combined_prob,
            combined_uncertainty=debate.conductor.combined_uncertainty,
            agent_votes=agent_votes,
            game_odds=game_odds,
        )
        if edge:
            edges.append(edge)

    # Sort by absolute edge descending
    edges.sort(key=lambda e: abs(e.edge), reverse=True)

    # Identify inefficiencies (|edge| > 5%)
    inefficiencies = [e for e in edges if abs(e.edge) > 0.05]

    # Build portfolio from Kelly recommendations
    portfolio = []
    for e in edges:
        if e.kelly_fraction > 0:
            position_size = round(bankroll * e.kelly_fraction, 2)
            portfolio.append({
                "game": f"#{e.seed_a} {e.team_a} vs #{e.seed_b} {e.team_b}",
                "region": e.region,
                "bet_side": e.bet_side,
                "position_size": position_size,
                "kelly_fraction": e.kelly_fraction,
                "edge": e.edge,
                "recommendation": e.recommendation,
            })

    # Sort portfolio by position size
    portfolio.sort(key=lambda p: p["position_size"], reverse=True)

    return MarketReport(
        edges=edges,
        total_games=len(debates),
        games_with_odds=games_with_odds,
        inefficiencies=inefficiencies,
        portfolio=portfolio,
    )


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------
def print_market_analysis(edge: MarketEdge):
    """Print market analysis for a single game."""
    direction = "swarm favors" if edge.edge > 0 else "market favors"
    favored = edge.team_a if edge.edge > 0 else edge.team_b

    lines = [
        f"  ## Market Analysis",
        f"  Swarm probability: {edge.team_a} {edge.swarm_prob:.0%} ± {edge.combined_uncertainty:.0%}",
        f"  Vegas implied probability: {edge.team_a} {edge.market_prob:.0%}",
        f"  Edge: {abs(edge.edge):.1%} ({direction} {favored})",
    ]

    if edge.vegas_spread is not None:
        lines.append(f"  Vegas spread: {edge.team_a} {edge.vegas_spread:+.1f}")

    if edge.contrarian_agents:
        agents_str = " and ".join(
            f"{name} ({contrib:+.0%} vs market)" for name, contrib in edge.contrarian_agents
        )
        lines.append(f"  Contrarian signal: {agents_str}")

    lines.append(f"  Recommendation: {edge.recommendation}")

    print("\n".join(lines))


def print_market_report(report: MarketReport, bankroll: float = 1000.0):
    """Print the full market inefficiency report."""
    print(f"\n{'='*70}")
    print(f"  MARKET INEFFICIENCY REPORT")
    print(f"  {report.games_with_odds}/{report.total_games} games with Vegas odds available")
    print(f"{'='*70}")

    if not report.inefficiencies:
        print("  No significant market inefficiencies detected (all edges < 5%)")
        print(f"{'='*70}")
        return

    # Top inefficiencies
    print(f"\n  TOP MARKET INEFFICIENCIES (edge > 5%)")
    print(f"  {'-'*65}")
    for i, e in enumerate(report.inefficiencies[:15], 1):
        direction = "underdog" if (
            (e.edge > 0 and e.seed_a > e.seed_b) or
            (e.edge < 0 and e.seed_b > e.seed_a)
        ) else "favorite"
        favored = e.team_a if e.edge > 0 else e.team_b
        print(
            f"  {i:>2}. #{e.seed_a} {e.team_a} vs #{e.seed_b} {e.team_b} ({e.region})"
        )
        print(
            f"      Swarm: {e.swarm_prob:.0%} | Market: {e.market_prob:.0%} | "
            f"Edge: {abs(e.edge):.1%} on {direction} ({favored})"
        )
        if e.contrarian_agents:
            agents_str = ", ".join(f"{n}" for n, _ in e.contrarian_agents[:3])
            print(f"      Contrarian agents: {agents_str}")
        print(f"      → {e.recommendation}")

    # Portfolio
    if report.portfolio:
        total_allocated = sum(p["position_size"] for p in report.portfolio)
        print(f"\n  BETTING PORTFOLIO (${bankroll:.0f} bankroll)")
        print(f"  {'-'*65}")
        for p in report.portfolio:
            print(
                f"  ${p['position_size']:>7.2f} on {p['bet_side']:<20} "
                f"(edge: {abs(p['edge']):.1%}, Kelly: {p['kelly_fraction']:.1%})"
            )
            print(f"           {p['game']}")
        print(f"  {'-'*65}")
        print(f"  Total allocated: ${total_allocated:.2f} / ${bankroll:.0f} "
              f"({total_allocated/bankroll:.0%})")
        print(f"  Cash reserve: ${bankroll - total_allocated:.2f}")

        # Expected ROI estimate (simplified)
        expected_profit = sum(
            p["position_size"] * abs(p["edge"]) * 2  # rough EV
            for p in report.portfolio
        )
        print(f"  Expected edge: +${expected_profit:.2f} "
              f"({expected_profit/total_allocated:.1%} ROI on allocated capital)")
    else:
        print("\n  No positions meet all criteria (edge > 5%, edge > 2x uncertainty, 2+ contrarian agents)")

    print(f"{'='*70}")


def generate_market_section(edge: MarketEdge) -> str:
    """Generate markdown market analysis section for debate transcripts."""
    direction = "swarm favors" if edge.edge > 0 else "market favors"
    favored = edge.team_a if edge.edge > 0 else edge.team_b

    lines = [
        "\n## Market Analysis\n",
        f"- Swarm probability: {edge.team_a} {edge.swarm_prob:.0%} ± {edge.combined_uncertainty:.0%}",
        f"- Vegas implied probability: {edge.team_a} {edge.market_prob:.0%}",
        f"- Edge: {abs(edge.edge):.1%} ({direction} {favored})",
    ]

    if edge.vegas_spread is not None:
        lines.append(f"- Vegas spread: {edge.team_a} {edge.vegas_spread:+.1f}")

    if edge.contrarian_agents:
        agents_str = " and ".join(
            f"{name} ({contrib:+.0%} vs market)" for name, contrib in edge.contrarian_agents
        )
        lines.append(f"- Contrarian signal: {agents_str}")

    lines.append(f"- Recommendation: {edge.recommendation}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick sanity check with synthetic data
    from odds_tracker import fetch_current_odds

    print("Market Analyzer — Standalone Test")
    print("=" * 50)

    # Simulate a game where swarm disagrees with market
    test_edge = MarketEdge(
        game_id="test_1",
        team_a="UCLA", team_b="UCF",
        seed_a=7, seed_b=10,
        region="East", round_name="R64",
        swarm_prob=0.58, market_prob=0.63,
        edge=-0.05,
        combined_uncertainty=0.11,
        agent_contributions={
            "Tempo Hawk": -0.03, "Iron Curtain": -0.08,
            "Glass Cannon": 0.02, "Road Dog": -0.12,
            "Whisper": -0.15, "Oracle": -0.01, "Streak": -0.06,
        },
        contrarian_agents=[("Whisper", -0.15), ("Road Dog", -0.12)],
        bet_side="UCF",
        kelly_fraction=0.02,
        recommendation="BET SMALL — 2.0% Kelly on UCF (edge: 5.0%, uncertainty: 11.0%)",
        vegas_spread=-2.5,
    )

    print_market_analysis(test_edge)
    print()
    print("Markdown output:")
    print(generate_market_section(test_edge))
