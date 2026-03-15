#!/usr/bin/env python3
"""
Live game result tracker for March Madness Agent Swarm.
Polls ESPN's public API for scores, marks results in Supabase,
and auto-updates agent accuracy stats.

Run as a cron job or long-running process during game windows.
Usage:
    python live_tracker.py              # one-shot check
    python live_tracker.py --watch      # poll every 5 minutes
    python live_tracker.py --watch -i 3 # poll every 3 minutes
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/scoreboard"
)
RESULTS_FILE = Path(__file__).parent / "live_results.json"


def fetch_scores() -> list[dict]:
    """Fetch current/recent game scores from ESPN."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(ESPN_SCOREBOARD_URL, params={
                "limit": 50,
                "groups": 100,  # NCAA tournament group
            })
            resp.raise_for_status()
            data = resp.json()

        games = []
        for event in data.get("events", []):
            competition = event.get("competitions", [{}])[0]
            status = competition.get("status", {})
            status_type = status.get("type", {}).get("name", "")
            is_final = status_type == "STATUS_FINAL"

            competitors = competition.get("competitors", [])
            if len(competitors) != 2:
                continue

            teams = {}
            for comp in competitors:
                team = comp.get("team", {})
                teams[comp.get("homeAway", "")] = {
                    "name": team.get("displayName", team.get("shortDisplayName", "")),
                    "abbreviation": team.get("abbreviation", ""),
                    "score": int(comp.get("score", 0)),
                    "seed": int(comp.get("curatedRank", {}).get("current", 0)),
                    "winner": comp.get("winner", False),
                }

            home = teams.get("home", {})
            away = teams.get("away", {})

            game = {
                "espn_id": event.get("id"),
                "name": event.get("name", ""),
                "short_name": event.get("shortName", ""),
                "home_team": home.get("name", ""),
                "away_team": away.get("name", ""),
                "home_score": home.get("score", 0),
                "away_score": away.get("score", 0),
                "home_seed": home.get("seed", 0),
                "away_seed": away.get("seed", 0),
                "is_final": is_final,
                "winner": (
                    home.get("name") if home.get("winner")
                    else away.get("name") if away.get("winner")
                    else None
                ),
                "status": status.get("type", {}).get("description", ""),
            }
            games.append(game)

        return games

    except Exception as e:
        print(f"ESPN fetch error: {e}")
        return []


def load_swarm_picks() -> dict:
    """Load the swarm's predictions from status.json and debates."""
    picks = {}

    # Try loading from Supabase-written game results
    results_dir = Path(__file__).parent / "debates"
    if not results_dir.exists():
        return picks

    # Also check if we have a games JSON
    games_file = Path(__file__).parent / "game_results.json"
    if games_file.exists():
        with open(games_file) as f:
            data = json.load(f)
        for game in data:
            key = _make_key(game.get("team_a", ""), game.get("team_b", ""))
            picks[key] = {
                "pick": game.get("pick"),
                "confidence": game.get("confidence"),
            }

    return picks


def _make_key(team_a: str, team_b: str) -> str:
    """Create a normalized key for a matchup."""
    teams = sorted([team_a.lower().strip(), team_b.lower().strip()])
    return f"{teams[0]}|{teams[1]}"


def _fuzzy_key(name_a: str, name_b: str, picks: dict) -> str | None:
    """Try to find a matching key in picks using fuzzy matching."""
    for key in picks:
        parts = key.split("|")
        if len(parts) != 2:
            continue
        a_match = name_a.lower() in parts[0] or parts[0] in name_a.lower()
        b_match = name_b.lower() in parts[1] or parts[1] in name_b.lower()
        a_match_rev = name_a.lower() in parts[1] or parts[1] in name_a.lower()
        b_match_rev = name_b.lower() in parts[0] or parts[0] in name_b.lower()
        if (a_match and b_match) or (a_match_rev and b_match_rev):
            return key
    return None


def check_results(scores: list[dict], picks: dict) -> list[dict]:
    """Compare final scores to swarm predictions."""
    results = []

    for game in scores:
        if not game["is_final"] or not game["winner"]:
            continue

        key = _make_key(game["home_team"], game["away_team"])
        swarm = picks.get(key)
        if not swarm:
            # Try fuzzy
            fk = _fuzzy_key(game["home_team"], game["away_team"], picks)
            if fk:
                swarm = picks[fk]

        if not swarm:
            continue

        correct = swarm["pick"].lower() in game["winner"].lower() or \
                  game["winner"].lower() in swarm["pick"].lower()

        is_upset = False
        if game["home_seed"] and game["away_seed"]:
            winner_seed = game["home_seed"] if game["winner"] == game["home_team"] else game["away_seed"]
            loser_seed = game["away_seed"] if game["winner"] == game["home_team"] else game["home_seed"]
            is_upset = winner_seed > loser_seed

        results.append({
            "matchup": game["short_name"] or game["name"],
            "winner": game["winner"],
            "score": f"{game['home_score']}-{game['away_score']}",
            "swarm_pick": swarm["pick"],
            "swarm_confidence": swarm["confidence"],
            "correct": correct,
            "upset": is_upset,
        })

    return results


def update_accuracy(results: list[dict]):
    """Update agent accuracy tracking based on game results."""
    import supabase_client

    # For now just write overall accuracy
    correct = sum(1 for r in results if r["correct"])
    total = len(results)

    if total > 0:
        supabase_client.write_status({
            "mode": "live_tracking",
            "games_checked": total,
            "correct": correct,
            "accuracy": round(100 * correct / total, 1),
            "upsets": sum(1 for r in results if r["upset"]),
        })


def save_results(all_results: list[dict]):
    """Persist results to JSON."""
    existing = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            existing = json.load(f)

    seen = {r["matchup"] for r in existing}
    for r in all_results:
        if r["matchup"] not in seen:
            existing.append(r)
            seen.add(r["matchup"])

    with open(RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def run_check():
    """Run a single check of scores vs predictions."""
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] Checking scores...")

    scores = fetch_scores()
    final_games = [g for g in scores if g["is_final"]]
    live_games = [g for g in scores if not g["is_final"] and g["status"] != "Scheduled"]
    upcoming = [g for g in scores if g["status"] == "Scheduled"]

    print(f"  Found: {len(final_games)} final, {len(live_games)} in progress, {len(upcoming)} upcoming")

    if live_games:
        print("\n  LIVE GAMES:")
        for g in live_games:
            print(f"    {g['short_name']}: {g['home_score']}-{g['away_score']} ({g['status']})")

    picks = load_swarm_picks()
    if not picks:
        print("  No swarm picks loaded. Run the swarm engine first.")
        return

    results = check_results(scores, picks)
    if results:
        print(f"\n  RESULTS vs SWARM:")
        correct = 0
        for r in results:
            mark = "+" if r["correct"] else "X"
            upset = " (UPSET!)" if r["upset"] else ""
            print(
                f"    [{mark}] {r['matchup']}: Winner={r['winner']}{upset} "
                f"| Swarm picked {r['swarm_pick']} ({r['swarm_confidence']}%)"
            )
            if r["correct"]:
                correct += 1

        print(f"\n  Swarm accuracy: {correct}/{len(results)} ({100*correct/len(results):.0f}%)")
        save_results(results)
        update_accuracy(results)
    else:
        print("  No matching completed games found.")


def main():
    parser = argparse.ArgumentParser(description="Live game result tracker")
    parser.add_argument("--watch", action="store_true", help="Continuous polling mode")
    parser.add_argument("-i", "--interval", type=int, default=5, help="Poll interval in minutes")
    args = parser.parse_args()

    if args.watch:
        print(f"Watching for results (polling every {args.interval} minutes). Ctrl+C to stop.")
        while True:
            try:
                run_check()
                print(f"\n  Next check in {args.interval} minutes...")
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
    else:
        run_check()


if __name__ == "__main__":
    main()
