#!/usr/bin/env python3
"""
Historical Backtesting Script for March Madness Agent Swarm

Runs the swarm engine in dry-run mode against past tournament brackets
where we know actual results, to measure agent accuracy and calibrate
the system.

Usage:
    python backtest.py
"""

import asyncio
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# Import from the swarm engine
from swarm_engine import (
    Game,
    GameDebate,
    AgentVote,
    ConductorDecision,
    build_agents,
    analyze_game,
    cost_tracker,
    AGENT_EMOJIS,
)


# ---------------------------------------------------------------------------
# Historical bracket data structures
# ---------------------------------------------------------------------------
@dataclass
class HistoricalGame:
    """A single historical game with known result."""
    team_a: str
    team_b: str
    seed_a: int
    seed_b: int
    region: str
    actual_winner: str
    stats_a: dict = field(default_factory=dict)
    stats_b: dict = field(default_factory=dict)


@dataclass
class HistoricalBracket:
    """A collection of historical games with known outcomes."""
    name: str
    year: int
    round_name: str
    games: list[HistoricalGame] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sample bracket: 8 games with realistic stats and known outcomes
# Includes 2 upsets (12 over 5, 14 over 3) and 6 chalk results.
# ---------------------------------------------------------------------------
SAMPLE_2025 = HistoricalBracket(
    name="SAMPLE_2025",
    year=2025,
    round_name="R64",
    games=[
        # Game 1: #1 vs #16 -- chalk (1 wins)
        HistoricalGame(
            team_a="Duke",
            team_b="American",
            seed_a=1,
            seed_b=16,
            region="East",
            actual_winner="Duke",
            stats_a={
                "adj_o": 123.5, "adj_d": 89.2, "adj_tempo": 68.1,
                "three_pt_pct": 38.2, "record": "30-3",
                "conference": "ACC", "kenpom_rank": 2,
            },
            stats_b={
                "adj_o": 101.2, "adj_d": 104.5, "adj_tempo": 65.3,
                "three_pt_pct": 33.1, "record": "21-12",
                "conference": "Patriot", "kenpom_rank": 184,
            },
        ),
        # Game 2: #8 vs #9 -- chalk (8 wins)
        HistoricalGame(
            team_a="Mississippi State",
            team_b="Baylor",
            seed_a=8,
            seed_b=9,
            region="East",
            actual_winner="Mississippi State",
            stats_a={
                "adj_o": 112.4, "adj_d": 96.7, "adj_tempo": 67.0,
                "three_pt_pct": 35.2, "record": "22-11",
                "conference": "SEC", "kenpom_rank": 42,
            },
            stats_b={
                "adj_o": 111.8, "adj_d": 97.1, "adj_tempo": 66.4,
                "three_pt_pct": 34.8, "record": "21-12",
                "conference": "Big 12", "kenpom_rank": 46,
            },
        ),
        # Game 3: #5 vs #12 -- UPSET (12 wins)
        HistoricalGame(
            team_a="Michigan",
            team_b="UC San Diego",
            seed_a=5,
            seed_b=12,
            region="East",
            actual_winner="UC San Diego",
            stats_a={
                "adj_o": 114.1, "adj_d": 96.8, "adj_tempo": 66.9,
                "three_pt_pct": 36.4, "record": "21-12",
                "conference": "Big Ten", "kenpom_rank": 34,
            },
            stats_b={
                "adj_o": 112.7, "adj_d": 95.3, "adj_tempo": 64.2,
                "three_pt_pct": 37.8, "record": "27-6",
                "conference": "Big West", "kenpom_rank": 41,
            },
        ),
        # Game 4: #4 vs #13 -- chalk (4 wins)
        HistoricalGame(
            team_a="Arizona",
            team_b="Akron",
            seed_a=4,
            seed_b=13,
            region="East",
            actual_winner="Arizona",
            stats_a={
                "adj_o": 118.7, "adj_d": 93.4, "adj_tempo": 69.2,
                "three_pt_pct": 36.5, "record": "26-7",
                "conference": "Big 12", "kenpom_rank": 8,
            },
            stats_b={
                "adj_o": 107.3, "adj_d": 100.2, "adj_tempo": 67.1,
                "three_pt_pct": 34.1, "record": "24-9",
                "conference": "MAC", "kenpom_rank": 89,
            },
        ),
        # Game 5: #3 vs #14 -- UPSET (14 wins)
        HistoricalGame(
            team_a="Wisconsin",
            team_b="Montana",
            seed_a=3,
            seed_b=14,
            region="East",
            actual_winner="Montana",
            stats_a={
                "adj_o": 116.2, "adj_d": 94.1, "adj_tempo": 63.8,
                "three_pt_pct": 35.9, "record": "25-8",
                "conference": "Big Ten", "kenpom_rank": 14,
            },
            stats_b={
                "adj_o": 109.4, "adj_d": 97.6, "adj_tempo": 68.5,
                "three_pt_pct": 38.3, "record": "27-5",
                "conference": "Big Sky", "kenpom_rank": 72,
            },
        ),
        # Game 6: #6 vs #11 -- chalk (6 wins)
        HistoricalGame(
            team_a="Missouri",
            team_b="Drake",
            seed_a=6,
            seed_b=11,
            region="East",
            actual_winner="Missouri",
            stats_a={
                "adj_o": 115.8, "adj_d": 95.5, "adj_tempo": 67.4,
                "three_pt_pct": 36.1, "record": "23-9",
                "conference": "SEC", "kenpom_rank": 22,
            },
            stats_b={
                "adj_o": 113.1, "adj_d": 96.8, "adj_tempo": 65.7,
                "three_pt_pct": 35.4, "record": "28-5",
                "conference": "MVC", "kenpom_rank": 30,
            },
        ),
        # Game 7: #2 vs #15 -- chalk (2 wins)
        HistoricalGame(
            team_a="Alabama",
            team_b="Robert Morris",
            seed_a=2,
            seed_b=15,
            region="East",
            actual_winner="Alabama",
            stats_a={
                "adj_o": 120.3, "adj_d": 91.8, "adj_tempo": 70.5,
                "three_pt_pct": 37.5, "record": "27-6",
                "conference": "SEC", "kenpom_rank": 5,
            },
            stats_b={
                "adj_o": 103.6, "adj_d": 103.9, "adj_tempo": 66.2,
                "three_pt_pct": 32.7, "record": "19-14",
                "conference": "Horizon", "kenpom_rank": 168,
            },
        ),
        # Game 8: #7 vs #10 -- chalk-ish but close (10 wins -- mild upset)
        HistoricalGame(
            team_a="UCLA",
            team_b="Arkansas",
            seed_a=7,
            seed_b=10,
            region="East",
            actual_winner="Arkansas",
            stats_a={
                "adj_o": 113.6, "adj_d": 96.2, "adj_tempo": 65.8,
                "three_pt_pct": 35.7, "record": "22-10",
                "conference": "Big Ten", "kenpom_rank": 31,
            },
            stats_b={
                "adj_o": 114.2, "adj_d": 95.5, "adj_tempo": 69.3,
                "three_pt_pct": 36.8, "record": "23-10",
                "conference": "SEC", "kenpom_rank": 28,
            },
        ),
    ],
)


# ---------------------------------------------------------------------------
# Convert historical games to swarm engine Game objects
# ---------------------------------------------------------------------------
def historical_to_game(hg: HistoricalGame, round_name: str = "R64") -> Game:
    """Convert a HistoricalGame to a swarm engine Game."""
    return Game(
        id=str(uuid.uuid4()),
        team_a=hg.team_a,
        team_b=hg.team_b,
        seed_a=hg.seed_a,
        seed_b=hg.seed_b,
        region=hg.region,
        round_name=round_name,
        stats_a=hg.stats_a,
        stats_b=hg.stats_b,
    )


def is_upset(seed_a: int, seed_b: int, winner: str, team_a: str, team_b: str) -> bool:
    """Check if a result is an upset (lower seed = higher number won)."""
    if seed_a == seed_b:
        return False
    higher_seed_team = team_a if seed_a < seed_b else team_b
    # team_a is always the higher seed (lower number) in our data
    if seed_a < seed_b:
        return winner != team_a
    else:
        return winner == team_a


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------
async def run_backtest(bracket: HistoricalBracket) -> dict:
    """
    Run the swarm engine in dry-run mode against a historical bracket
    and collect results for analysis.
    """
    print("=" * 70)
    print(f"  BACKTEST: {bracket.name} ({bracket.year})")
    print(f"  Games: {len(bracket.games)} | Round: {bracket.round_name}")
    print("=" * 70)
    print()

    agents = build_agents()
    agent_accuracy: dict[str, dict] = {}
    groupthink_tracker: dict = {"unanimous": 0, "total": 0}
    agent_memory: dict[str, list[str]] = {}

    results = []
    total = len(bracket.games)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        for i, hg in enumerate(bracket.games, 1):
            game = historical_to_game(hg, bracket.round_name)

            try:
                debate = await analyze_game(
                    client=client,
                    game=game,
                    agents=agents,
                    agent_accuracy=agent_accuracy,
                    game_index=i,
                    total_games=total,
                    dry_run=True,
                    groupthink_tracker=groupthink_tracker,
                    agent_memory=agent_memory,
                )
            except Exception as exc:
                print(
                    f"  [ERROR] Game {i}: #{hg.seed_a} {hg.team_a} vs "
                    f"#{hg.seed_b} {hg.team_b} failed: {exc}"
                )
                print()
                continue

            results.append({
                "game": hg,
                "debate": debate,
                "swarm_pick": debate.conductor.pick if debate.conductor else None,
                "swarm_confidence": debate.conductor.confidence if debate.conductor else 0,
                "actual_winner": hg.actual_winner,
                "correct": (
                    debate.conductor.pick == hg.actual_winner
                    if debate.conductor
                    else False
                ),
            })

            status = "CORRECT" if results[-1]["correct"] else "WRONG"
            print(
                f"  [{status}] #{hg.seed_a} {hg.team_a} vs #{hg.seed_b} {hg.team_b} "
                f"| Picked: {results[-1]['swarm_pick']} "
                f"({results[-1]['swarm_confidence']}%) "
                f"| Actual: {hg.actual_winner}"
            )
            print()

    return {
        "bracket": bracket,
        "results": results,
        "agents": agents,
        "groupthink": groupthink_tracker,
    }


# ---------------------------------------------------------------------------
# Analysis and reporting
# ---------------------------------------------------------------------------
def generate_report(data: dict) -> str:
    """Generate a full calibration report from backtest results."""
    bracket = data["bracket"]
    results = data["results"]
    agents_list = data["agents"]
    groupthink = data["groupthink"]

    total_games = len(results)
    correct_games = sum(1 for r in results if r["correct"])
    overall_accuracy = correct_games / total_games if total_games > 0 else 0

    lines = []
    lines.append("=" * 70)
    lines.append("  BACKTEST CALIBRATION REPORT")
    lines.append(f"  Bracket: {bracket.name} ({bracket.year})")
    lines.append(f"  Games tested: {total_games}")
    lines.append("=" * 70)
    lines.append("")

    # --- Overall accuracy ---
    lines.append("OVERALL SWARM ACCURACY")
    lines.append("-" * 40)
    lines.append(f"  Correct: {correct_games}/{total_games} ({overall_accuracy:.1%})")
    lines.append("")

    # --- Per-agent accuracy ---
    lines.append("PER-AGENT ACCURACY")
    lines.append("-" * 40)

    agent_names = [a.name for a in agents_list]
    agent_stats: dict[str, dict] = {
        name: {"correct": 0, "total": 0, "confidences": []}
        for name in agent_names
    }

    for r in results:
        debate = r["debate"]
        actual = r["actual_winner"]
        for vote in debate.votes:
            if vote.error or not vote.pick:
                continue
            name = vote.agent_name
            if name not in agent_stats:
                agent_stats[name] = {"correct": 0, "total": 0, "confidences": []}
            agent_stats[name]["total"] += 1
            agent_stats[name]["confidences"].append(vote.confidence)
            if vote.pick == actual:
                agent_stats[name]["correct"] += 1

    # Sort by accuracy descending
    sorted_agents = sorted(
        agent_stats.items(),
        key=lambda x: (x[1]["correct"] / x[1]["total"]) if x[1]["total"] > 0 else 0,
        reverse=True,
    )

    for name, stats in sorted_agents:
        if stats["total"] == 0:
            continue
        acc = stats["correct"] / stats["total"]
        avg_conf = sum(stats["confidences"]) / len(stats["confidences"]) if stats["confidences"] else 0
        emoji = AGENT_EMOJIS.get(name, "")
        lines.append(
            f"  {emoji} {name:18s} {stats['correct']}/{stats['total']} "
            f"({acc:.1%})  avg confidence: {avg_conf:.0f}%"
        )

    lines.append("")

    # --- Conductor accuracy ---
    lines.append("CONDUCTOR (FINAL DECISION) ACCURACY")
    lines.append("-" * 40)
    lines.append(f"  {correct_games}/{total_games} ({overall_accuracy:.1%})")
    lines.append("")

    # --- Calibration analysis ---
    lines.append("CALIBRATION ANALYSIS")
    lines.append("-" * 40)
    lines.append("  (When the swarm was X% confident, how often were they right?)")
    lines.append("")

    confidence_buckets = {
        "90-99%": {"correct": 0, "total": 0},
        "80-89%": {"correct": 0, "total": 0},
        "70-79%": {"correct": 0, "total": 0},
        "60-69%": {"correct": 0, "total": 0},
        "50-59%": {"correct": 0, "total": 0},
    }

    for r in results:
        conf = r["swarm_confidence"]
        correct = r["correct"]
        if conf >= 90:
            bucket = "90-99%"
        elif conf >= 80:
            bucket = "80-89%"
        elif conf >= 70:
            bucket = "70-79%"
        elif conf >= 60:
            bucket = "60-69%"
        else:
            bucket = "50-59%"
        confidence_buckets[bucket]["total"] += 1
        if correct:
            confidence_buckets[bucket]["correct"] += 1

    for bucket_name, bucket_data in confidence_buckets.items():
        if bucket_data["total"] == 0:
            lines.append(f"  {bucket_name}: no games in this range")
        else:
            acc = bucket_data["correct"] / bucket_data["total"]
            lines.append(
                f"  {bucket_name}: {bucket_data['correct']}/{bucket_data['total']} "
                f"correct ({acc:.1%})"
            )

    lines.append("")

    # --- Upset detection ---
    lines.append("UPSET DETECTION")
    lines.append("-" * 40)

    actual_upsets = []
    predicted_upsets = []
    upset_detection_correct = 0

    for r in results:
        hg = r["game"]
        # An upset is when the lower-seeded team (higher seed number) wins
        higher_seed_team = hg.team_a if hg.seed_a < hg.seed_b else hg.team_b
        is_actual_upset = hg.actual_winner != higher_seed_team

        swarm_pick = r["swarm_pick"]
        swarm_predicted_upset = swarm_pick != higher_seed_team if swarm_pick else False

        if is_actual_upset:
            actual_upsets.append(hg)
            if swarm_predicted_upset:
                upset_detection_correct += 1
                predicted_upsets.append(hg)

    lines.append(f"  Actual upsets in sample: {len(actual_upsets)}")
    for u in actual_upsets:
        lines.append(f"    #{u.seed_b} {u.actual_winner} over #{u.seed_a} {u.team_a}")

    lines.append(f"  Upsets correctly predicted: {upset_detection_correct}/{len(actual_upsets)}")
    if actual_upsets:
        detection_rate = upset_detection_correct / len(actual_upsets)
        lines.append(f"  Upset detection rate: {detection_rate:.1%}")
    else:
        lines.append("  Upset detection rate: N/A (no upsets in sample)")

    lines.append("")

    # --- Chalk bias analysis ---
    lines.append("CHALK BIAS ANALYSIS")
    lines.append("-" * 40)
    chalk_picks = sum(
        1 for r in results
        if r["swarm_pick"] == (
            r["game"].team_a if r["game"].seed_a < r["game"].seed_b else r["game"].team_b
        )
    )
    chalk_rate = chalk_picks / total_games if total_games > 0 else 0
    actual_chalk = total_games - len(actual_upsets)
    actual_chalk_rate = actual_chalk / total_games if total_games > 0 else 0
    lines.append(f"  Swarm picked chalk: {chalk_picks}/{total_games} ({chalk_rate:.1%})")
    lines.append(f"  Actual chalk results: {actual_chalk}/{total_games} ({actual_chalk_rate:.1%})")
    if chalk_rate > actual_chalk_rate + 0.1:
        lines.append("  WARNING: Swarm has significant chalk bias. Consider boosting upset-leaning agents.")
    lines.append("")

    # --- Game-by-game results ---
    lines.append("GAME-BY-GAME RESULTS")
    lines.append("-" * 40)
    for i, r in enumerate(results, 1):
        hg = r["game"]
        status = "OK" if r["correct"] else "MISS"
        lines.append(
            f"  {i}. [{status}] #{hg.seed_a} {hg.team_a} vs #{hg.seed_b} {hg.team_b} "
            f"| Pick: {r['swarm_pick']} ({r['swarm_confidence']}%) "
            f"| Actual: {hg.actual_winner}"
        )
    lines.append("")

    # --- Groupthink ---
    lines.append("GROUPTHINK METRICS")
    lines.append("-" * 40)
    if groupthink["total"] > 0:
        gt_rate = groupthink["unanimous"] / groupthink["total"]
        lines.append(
            f"  Unanimous votes: {groupthink['unanimous']}/{groupthink['total']} ({gt_rate:.1%})"
        )
        if gt_rate > 0.6:
            lines.append("  WARNING: High unanimity. Agents may not be sufficiently differentiated.")
    else:
        lines.append("  No groupthink data available.")
    lines.append("")

    # --- Recommendations ---
    lines.append("RECOMMENDATIONS")
    lines.append("-" * 40)

    # Find best and worst agents
    if sorted_agents:
        best_name, best_stats = sorted_agents[0]
        worst_name, worst_stats = sorted_agents[-1]
        if best_stats["total"] > 0 and worst_stats["total"] > 0:
            best_acc = best_stats["correct"] / best_stats["total"]
            worst_acc = worst_stats["correct"] / worst_stats["total"]
            lines.append(f"  - Best agent: {best_name} ({best_acc:.1%} accuracy)")
            lines.append(f"    Consider increasing weight in Conductor's decision.")
            lines.append(f"  - Worst agent: {worst_name} ({worst_acc:.1%} accuracy)")
            lines.append(f"    Consider decreasing weight or adjusting system prompt.")

    if chalk_rate > actual_chalk_rate + 0.1:
        lines.append(
            "  - The swarm is too chalky. Consider:"
        )
        lines.append("    * Lowering Glass Cannon and Whisper confidence thresholds for upsets")
        lines.append("    * Adding an upset-specialist agent")
        lines.append("    * Reducing Oracle's historical base rate influence for 5-12 and 3-14 games")

    if len(actual_upsets) > 0 and upset_detection_correct == 0:
        lines.append(
            "  - CRITICAL: Swarm detected 0 upsets. The system needs calibration to "
            "avoid always picking chalk."
        )

    lines.append("")
    lines.append(f"Cost tracker: {cost_tracker.summary()}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def async_main():
    """Run the full backtest pipeline."""
    data = await run_backtest(SAMPLE_2025)
    report = generate_report(data)

    print()
    print(report)

    # Save report to file
    report_path = Path(__file__).parent / "backtest_report.txt"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Report saved to: {report_path}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
