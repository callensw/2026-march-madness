#!/usr/bin/env python3
"""
Populate mm_players and mm_teams.key_players in Supabase
with 2025-26 season player data for all 68 tournament teams.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TOURNAMENT_ID = "3e52e2dd-1c70-441c-b46c-766e7b0ee28f"

# Collect all player data from batch files
all_players = []

from player_data_batch1 import players_batch1
from player_data_batch2 import players_batch2
from player_data_batch3 import players_batch3

all_players.extend(players_batch1)
all_players.extend(players_batch2)
all_players.extend(players_batch3)

# Import files agents wrote directly
from west_region_players import west_region_players
all_players.extend(west_region_players)
from south_region_players import south_region_players
all_players.extend(south_region_players)

# Import remaining batches
for mod_name in ['player_data_batch4', 'player_data_batch5', 'player_data_batch6', 'player_data_batch7']:
    try:
        mod = __import__(mod_name)
        for attr in dir(mod):
            val = getattr(mod, attr)
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and 'team_name' in val[0]:
                all_players.extend(val)
    except ImportError:
        print(f"  Skipping {mod_name} (not found)")

def normalize_pct(val):
    """Normalize percentage: if > 1, it's in whole-number format (e.g. 43.5 -> 0.435)"""
    if val is None:
        return 0.0
    if val > 1.0:
        return round(val / 100.0, 4)
    return round(val, 4)


def build_key_players_string(team_name, players):
    """Build the key_players summary string for a team."""
    team_players = [p for p in players if p['team_name'] == team_name]
    # Sort by PPG descending
    team_players.sort(key=lambda p: p.get('points_per_game', 0), reverse=True)

    lines = []
    injured_lines = []
    for i, p in enumerate(team_players[:5], 1):
        ppg = p.get('points_per_game', 0)
        rpg = p.get('rebounds_per_game', 0)
        apg = p.get('assists_per_game', 0)
        pos = p.get('position', '?')
        year = p.get('year', '?')
        role = p.get('role_description', '')
        # Truncate role to keep it concise
        if len(role) > 50:
            role = role[:47] + '...'

        if p.get('is_injured') and p.get('injury_details'):
            injured_lines.append(
                f"MISSING: {p['player_name']} ({ppg} PPG, {rpg} RPG) — {p['injury_details']}"
            )
        else:
            stat_parts = [f"{ppg} PPG"]
            if rpg >= 5.0:
                stat_parts.append(f"{rpg} RPG")
            if apg >= 4.0:
                stat_parts.append(f"{apg} APG")
            draft = " [NBA prospect]" if p.get('nba_draft_prospect') else ""
            lines.append(
                f"{i}. {p['player_name']} ({pos}, {year}, {', '.join(stat_parts)}) — {role}{draft}"
            )

    result = "; ".join(lines)
    if injured_lines:
        result += ". " + "; ".join(injured_lines)
    return result


def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY required in .env")
        sys.exit(1)

    from supabase import create_client
    client = create_client(url, key)

    print(f"Total players collected: {len(all_players)}")

    # Get unique teams
    teams = set(p['team_name'] for p in all_players)
    print(f"Teams with player data: {len(teams)}")

    # Normalize percentages and build rows
    rows = []
    for p in all_players:
        rows.append({
            "tournament_id": TOURNAMENT_ID,
            "team_name": p["team_name"],
            "player_name": p["player_name"],
            "position": p.get("position"),
            "year": p.get("year"),
            "points_per_game": p.get("points_per_game", 0),
            "rebounds_per_game": p.get("rebounds_per_game", 0),
            "assists_per_game": p.get("assists_per_game", 0),
            "fg_pct": normalize_pct(p.get("fg_pct", 0)),
            "three_pt_pct": normalize_pct(p.get("three_pt_pct", 0)),
            "ft_pct": normalize_pct(p.get("ft_pct", 0)),
            "is_starter": p.get("is_starter", False),
            "is_injured": p.get("is_injured", False),
            "injury_details": p.get("injury_details"),
            "is_key_player": True,
            "role_description": p.get("role_description"),
            "nba_draft_prospect": p.get("nba_draft_prospect", False),
        })

    # Clear existing player data for this tournament
    print("Clearing existing player data...")
    client.table("mm_players").delete().eq("tournament_id", TOURNAMENT_ID).execute()

    # Insert in batches of 50
    print("Inserting player data...")
    for i in range(0, len(rows), 50):
        batch = rows[i:i+50]
        client.table("mm_players").insert(batch).execute()
        print(f"  Inserted {min(i+50, len(rows))}/{len(rows)} players")

    # Build and update key_players for each team
    print("\nUpdating key_players in mm_teams...")
    for team_name in sorted(teams):
        kp_string = build_key_players_string(team_name, all_players)
        result = client.table("mm_teams").update(
            {"key_players": kp_string}
        ).eq("name", team_name).execute()
        if result.data:
            print(f"  ✓ {team_name}")
        else:
            print(f"  ✗ {team_name} (not found in mm_teams)")

    # Summary
    injured_count = sum(1 for p in all_players if p.get('is_injured'))
    draft_count = sum(1 for p in all_players if p.get('nba_draft_prospect'))
    print(f"\n{'='*60}")
    print(f"Total players: {len(all_players)}")
    print(f"Teams covered: {len(teams)}")
    print(f"Injured players: {injured_count}")
    print(f"NBA draft prospects: {draft_count}")

    # Show 3 example key_players strings
    print(f"\n--- Example key_players strings ---")
    for team_name in ["Duke", "Texas Tech", "Florida"]:
        if team_name in teams:
            kp = build_key_players_string(team_name, all_players)
            print(f"\n{team_name}:\n  {kp}")

    print(f"\n{'='*60}")
    print("Done!")


if __name__ == "__main__":
    main()
