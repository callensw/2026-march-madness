#!/usr/bin/env python3
"""
Vegas odds tracker for March Madness Agent Swarm.
Fetches opening lines and compares to swarm confidence.
Uses The Odds API (free tier: 500 requests/month).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "basketball_ncaab"
ODDS_FILE = Path(__file__).parent / "odds_data.json"


def get_api_key() -> str | None:
    key = os.getenv("ODDS_API_KEY", "")
    if not key or "xxxxx" in key:
        return None
    return key


def fetch_current_odds() -> list[dict]:
    """Fetch current NCAA basketball odds from The Odds API."""
    api_key = get_api_key()
    if not api_key:
        print("No ODDS_API_KEY configured. Add it to .env for Vegas line comparison.")
        print("Get a free key at: https://the-odds-api.com/ (500 requests/month free)")
        return _load_cached()

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{ODDS_API_URL}/{SPORT}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "us",
                    "markets": "spreads,h2h",
                    "oddsFormat": "american",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Cache the response
            with open(ODDS_FILE, "w") as f:
                json.dump({
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "games": data,
                }, f, indent=2)

            remaining = resp.headers.get("x-requests-remaining", "?")
            print(f"Fetched odds for {len(data)} games ({remaining} API requests remaining)")
            return data

    except Exception as e:
        print(f"Odds fetch failed: {e}")
        return _load_cached()


def _load_cached() -> list[dict]:
    """Load cached odds data if available."""
    if ODDS_FILE.exists():
        with open(ODDS_FILE) as f:
            data = json.load(f)
        print(f"Using cached odds from {data.get('fetched_at', 'unknown')}")
        return data.get("games", [])
    return []


def find_game_odds(team_a: str, team_b: str, odds_data: list[dict]) -> dict | None:
    """Find odds for a specific matchup."""
    a_lower = team_a.lower()
    b_lower = team_b.lower()

    for game in odds_data:
        home = game.get("home_team", "").lower()
        away = game.get("away_team", "").lower()

        if (a_lower in home or home in a_lower or
            a_lower in away or away in a_lower) and \
           (b_lower in home or home in b_lower or
            b_lower in away or away in b_lower):
            return _parse_odds(game)

    return None


def _parse_odds(game: dict) -> dict:
    """Parse odds data into a clean format."""
    result = {
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "commence_time": game.get("commence_time"),
        "spreads": {},
        "moneylines": {},
    }

    for bookmaker in game.get("bookmakers", []):
        book_name = bookmaker.get("title", "Unknown")
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                for outcome in market.get("outcomes", []):
                    team = outcome["name"]
                    result["spreads"][team] = {
                        "point": outcome.get("point", 0),
                        "price": outcome.get("price", 0),
                        "book": book_name,
                    }
            elif market["key"] == "h2h":
                for outcome in market.get("outcomes", []):
                    team = outcome["name"]
                    result["moneylines"][team] = {
                        "price": outcome.get("price", 0),
                        "book": book_name,
                    }

    return result


def american_to_implied_prob(american_odds: int) -> float:
    """Convert American odds to implied probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def spread_to_implied_prob(spread: float) -> float:
    """
    Rough conversion from point spread to win probability.
    Based on historical NCAA data: each point of spread ≈ 3% win probability shift.
    """
    return min(0.97, max(0.03, 0.50 + (-spread * 0.03)))


def compare_swarm_to_vegas(
    swarm_pick: str,
    swarm_confidence: int,
    game_odds: dict,
    team_a: str,
    team_b: str,
) -> dict:
    """
    Compare swarm prediction to Vegas lines.
    Returns a comparison dict with the delta.
    """
    swarm_prob = swarm_confidence / 100.0

    # Try to find spread for the picked team
    vegas_prob = None
    vegas_spread = None

    for team_key, spread_data in game_odds.get("spreads", {}).items():
        if team_a.lower() in team_key.lower() or team_key.lower() in team_a.lower():
            if swarm_pick == team_a:
                vegas_spread = spread_data["point"]
                vegas_prob = spread_to_implied_prob(spread_data["point"])
            break
        if team_b.lower() in team_key.lower() or team_key.lower() in team_b.lower():
            if swarm_pick == team_b:
                vegas_spread = spread_data["point"]
                vegas_prob = spread_to_implied_prob(spread_data["point"])
            break

    # Fallback to moneyline
    if vegas_prob is None:
        for team_key, ml_data in game_odds.get("moneylines", {}).items():
            pick_lower = swarm_pick.lower()
            if pick_lower in team_key.lower() or team_key.lower() in pick_lower:
                vegas_prob = american_to_implied_prob(ml_data["price"])
                break

    if vegas_prob is None:
        return {"available": False}

    delta = swarm_prob - vegas_prob
    direction = "more bullish" if delta > 0 else "more bearish"

    return {
        "available": True,
        "swarm_pick": swarm_pick,
        "swarm_prob": round(swarm_prob * 100, 1),
        "vegas_prob": round(vegas_prob * 100, 1),
        "vegas_spread": vegas_spread,
        "delta": round(delta * 100, 1),
        "direction": direction,
        "summary": (
            f"Swarm: {swarm_prob*100:.0f}% on {swarm_pick} | "
            f"Vegas implied: {vegas_prob*100:.0f}% | "
            f"Delta: {abs(delta)*100:.0f}pp {direction}"
        ),
    }


def print_odds_comparison(comparisons: list[dict]):
    """Print a formatted odds comparison table."""
    print("\n" + "=" * 70)
    print("SWARM vs VEGAS COMPARISON")
    print("=" * 70)

    for c in comparisons:
        if not c.get("available"):
            continue
        delta_str = f"+{c['delta']}" if c['delta'] > 0 else str(c['delta'])
        flag = " <<<" if abs(c['delta']) > 10 else ""
        print(f"  {c['summary']}{flag}")

    big_deltas = [c for c in comparisons if c.get("available") and abs(c.get("delta", 0)) > 10]
    if big_deltas:
        print(f"\n  {len(big_deltas)} games where swarm disagrees with Vegas by >10 points")


if __name__ == "__main__":
    print("Fetching current odds...")
    odds = fetch_current_odds()
    if odds:
        print(f"Got odds for {len(odds)} games")
    else:
        print("No odds data available. Configure ODDS_API_KEY in .env")
