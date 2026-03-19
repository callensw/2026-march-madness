#!/usr/bin/env python3
"""
Team data scraper for March Madness Agent Swarm.
Scrapes from Barttorvik (barttorvik.com) or falls back to manual entry.
"""

import json
import sys
from difflib import SequenceMatcher

import httpx
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "team_data_2026.json"

BARTTORVIK_URL = "https://barttorvik.com/trank.php?year=2026&conyes=1&json=1"


def scrape_barttorvik() -> list[dict] | None:
    """Attempt to scrape team data from Barttorvik's JSON endpoint."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "application/json, text/html",
            }
            resp = client.get(BARTTORVIK_URL, headers=headers)
            resp.raise_for_status()

            # Barttorvik sometimes returns JSON directly
            try:
                data = resp.json()
            except Exception:
                print("Response was not JSON. Barttorvik may have bot protection.")
                return None

            teams = []
            for row in data:
                # Barttorvik JSON fields vary; adapt as needed
                team = {
                    "name": row.get("team", row.get("Team", "")),
                    "seed": None,
                    "region": None,
                    "adj_o": row.get("adjoe", row.get("AdjOE", 0)),
                    "adj_d": row.get("adjde", row.get("AdjDE", 0)),
                    "adj_tempo": row.get("adjt", row.get("AdjTempo", 0)),
                    "record": row.get("rec", row.get("Rec", "")),
                    "conference": row.get("conf", row.get("Conf", "")),
                    "barthag": row.get("barthag", row.get("Barthag", 0)),
                    "kenpom_rank": row.get("rk", row.get("Rank", 0)),
                    "three_pt_pct": row.get("3p_pct", row.get("3P%", 0)),
                }
                teams.append(team)
            return teams

    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code}")
        return None
    except httpx.RequestError as e:
        print(f"Request error: {e}")
        return None


def build_team_entry(
    name: str,
    seed: int | None = None,
    region: str | None = None,
    adj_o: float = 0,
    adj_d: float = 0,
    adj_tempo: float = 0,
    record: str = "",
    conference: str = "",
    kenpom_rank: int = 0,
    three_pt_pct: float = 0,
) -> dict:
    """Build a single team dict formatted for bracket_loader.py."""
    return {
        "name": name,
        "seed": seed,
        "region": region,
        "adj_o": adj_o,
        "adj_d": adj_d,
        "adj_tempo": adj_tempo,
        "record": record,
        "conference": conference,
        "kenpom_rank": kenpom_rank,
        "three_pt_pct": three_pt_pct,
    }


def lookup_teams(team_names: list[str], all_teams: list[dict]) -> dict:
    """
    Given a list of team names, find them in scraped data and return
    a dict keyed by team name with bracket_loader.py-compatible entries.
    """
    name_index = {}
    for t in all_teams:
        name_index[t["name"].lower().strip()] = t

    result = {}
    for name in team_names:
        key = name.lower().strip()
        if key in name_index:
            result[name] = name_index[key]
        else:
            # Use similarity matching: require >= 80% or exact word boundary match
            best_match = None
            best_ratio = 0.0
            word_boundary_match = None
            key_words = set(key.split())
            for k, t in name_index.items():
                k_words = set(k.split())
                # Word boundary match: all words in one name appear in the other
                if key_words and k_words and (key_words <= k_words or k_words <= key_words):
                    word_boundary_match = t
                    break
                ratio = SequenceMatcher(None, key, k).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = t
            if word_boundary_match:
                result[name] = word_boundary_match
            elif best_match and best_ratio >= 0.80:
                result[name] = best_match
            else:
                print(f"  Warning: '{name}' not found in scraped data (best similarity: {best_ratio:.0%})")
                result[name] = build_team_entry(name)
    return result


def fetch_injury_reports() -> list[dict]:
    """
    Fetch injury/availability info from ESPN's API.
    Falls back gracefully if the endpoint is unavailable.
    """
    injuries = []
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            # ESPN's public API for men's college basketball
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/news"
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for article in data.get("articles", []):
                headline = article.get("headline", "").lower()
                if any(kw in headline for kw in ["injury", "out", "doubtful", "questionable", "status", "return"]):
                    injuries.append({
                        "headline": article.get("headline"),
                        "description": article.get("description", ""),
                        "published": article.get("published", ""),
                        "link": article.get("links", {}).get("web", {}).get("href", ""),
                    })
    except Exception as e:
        print(f"Could not fetch injury reports: {e}")

    return injuries


def manual_entry_template() -> list[dict]:
    """Return a template for manual data entry with expected 2026 top teams."""
    # Placeholder data - fill in after Selection Sunday bracket reveal
    return [
        build_team_entry("Duke", seed=1, region="East", adj_o=123.5, adj_d=89.2, adj_tempo=68.1, record="30-3", conference="ACC", kenpom_rank=1, three_pt_pct=38.2),
        build_team_entry("Michigan", seed=1, region="Midwest", adj_o=121.8, adj_d=90.1, adj_tempo=67.5, record="29-4", conference="Big Ten", kenpom_rank=2, three_pt_pct=37.8),
        build_team_entry("Arizona", seed=1, region="West", adj_o=122.1, adj_d=91.0, adj_tempo=69.2, record="28-4", conference="Big 12", kenpom_rank=3, three_pt_pct=36.5),
        build_team_entry("Florida", seed=1, region="South", adj_o=120.9, adj_d=89.8, adj_tempo=66.8, record="29-3", conference="SEC", kenpom_rank=4, three_pt_pct=37.1),
    ]


def main():
    print("=" * 60)
    print("March Madness Agent Swarm - Team Data Scraper")
    print("=" * 60)

    # Try scraping Barttorvik
    print("\n[1/3] Attempting to scrape Barttorvik...")
    teams = scrape_barttorvik()

    if teams:
        print(f"  ✓ Scraped {len(teams)} teams from Barttorvik")
    else:
        print("  ✗ Barttorvik scrape failed. Using manual entry template.")
        print("    (Fill in real data after the bracket drops at 6 PM ET)")
        teams = manual_entry_template()

    # Fetch injury reports
    print("\n[2/3] Fetching injury reports from ESPN...")
    injuries = fetch_injury_reports()
    if injuries:
        print(f"  ✓ Found {len(injuries)} injury-related reports")
    else:
        print("  No injury reports found (or ESPN API unavailable)")

    # Save output
    print(f"\n[3/3] Saving to {OUTPUT_FILE}...")
    output = {
        "scrape_source": "barttorvik" if len(teams) > 10 else "manual_template",
        "team_count": len(teams),
        "teams": teams,
        "injury_reports": injuries,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  ✓ Saved {len(teams)} teams to {OUTPUT_FILE}")
    print("\nDone! Run fill_bracket.py to build the tournament bracket.")


if __name__ == "__main__":
    main()
