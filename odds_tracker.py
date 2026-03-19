#!/usr/bin/env python3
"""
Vegas odds tracker for March Madness Agent Swarm.
Fetches opening lines and compares to swarm confidence.
Uses The Odds API (free tier: 500 requests/month).
"""

import json
import logging
import os
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger("swarm")

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "basketball_ncaab"
ODDS_FILE = Path(__file__).parent / "odds_data.json"

# Track remaining API quota so callers can check before making requests
_requests_remaining: int | None = None


def get_requests_remaining() -> int | None:
    """Return the last known remaining API request quota, or None if unknown."""
    return _requests_remaining


def get_api_key() -> str | None:
    key = os.getenv("ODDS_API_KEY", "")
    if not key or "xxxxx" in key:
        return None
    return key


def fetch_current_odds() -> list[dict]:
    """Fetch current NCAA basketball odds from The Odds API."""
    api_key = get_api_key()
    if not api_key:
        log.warning("No ODDS_API_KEY configured. Add it to .env for Vegas line comparison.")
        log.warning("Get a free key at: https://the-odds-api.com/ (500 requests/month free)")
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

            global _requests_remaining
            remaining_raw = resp.headers.get("x-requests-remaining")
            if remaining_raw is not None:
                try:
                    _requests_remaining = int(remaining_raw)
                except ValueError:
                    _requests_remaining = None

            remaining_display = remaining_raw if remaining_raw is not None else "?"
            log.info(f"Fetched odds for {len(data)} games ({remaining_display} API requests remaining)")

            if _requests_remaining is not None and _requests_remaining < 10:
                log.warning(
                    f"Odds API quota low: only {_requests_remaining} requests remaining!"
                )

            return data

    except Exception as e:
        log.error(f"Odds fetch failed: {e}")
        return _load_cached()


def _load_cached() -> list[dict]:
    """Load cached odds data if available."""
    if ODDS_FILE.exists():
        with open(ODDS_FILE) as f:
            data = json.load(f)
        log.info(f"Using cached odds from {data.get('fetched_at', 'unknown')}")
        return data.get("games", [])
    return []


def _team_match(name_a: str, name_b: str, threshold: float = 0.80) -> bool:
    """
    Check if two team names match using either:
    - Exact word boundary matching (one name is a full word in the other), or
    - SequenceMatcher similarity >= threshold (default 80%).
    """
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    if a == b:
        return True
    # Word boundary match: check if one name appears as a complete word in the other
    a_words = set(a.split())
    b_words = set(b.split())
    if a_words and b_words and (a_words <= b_words or b_words <= a_words):
        return True
    # Fuzzy similarity
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio >= threshold


def find_game_odds(team_a: str, team_b: str, odds_data: list[dict]) -> dict | None:
    """Find odds for a specific matchup."""
    for game in odds_data:
        home = game.get("home_team", "")
        away = game.get("away_team", "")

        a_matches = _team_match(team_a, home) or _team_match(team_a, away)
        b_matches = _team_match(team_b, home) or _team_match(team_b, away)

        if a_matches and b_matches:
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
        if _team_match(team_a, team_key):
            if swarm_pick == team_a:
                vegas_spread = spread_data["point"]
                vegas_prob = spread_to_implied_prob(spread_data["point"])
            break
        if _team_match(team_b, team_key):
            if swarm_pick == team_b:
                vegas_spread = spread_data["point"]
                vegas_prob = spread_to_implied_prob(spread_data["point"])
            break

    # Fallback to moneyline
    if vegas_prob is None:
        for team_key, ml_data in game_odds.get("moneylines", {}).items():
            if _team_match(swarm_pick, team_key):
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
    log.info("\n" + "=" * 70)
    log.info("SWARM vs VEGAS COMPARISON")
    log.info("=" * 70)

    for c in comparisons:
        if not c.get("available"):
            continue
        delta_str = f"+{c['delta']}" if c['delta'] > 0 else str(c['delta'])
        flag = " <<<" if abs(c['delta']) > 10 else ""
        log.info(f"  {c['summary']}{flag}")

    big_deltas = [c for c in comparisons if c.get("available") and abs(c.get("delta", 0)) > 10]
    if big_deltas:
        log.info(f"\n  {len(big_deltas)} games where swarm disagrees with Vegas by >10 points")


if __name__ == "__main__":
    log.info("Fetching current odds...")
    odds = fetch_current_odds()
    if odds:
        log.info(f"Got odds for {len(odds)} games")
    else:
        log.warning("No odds data available. Configure ODDS_API_KEY in .env")
