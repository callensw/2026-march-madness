#!/usr/bin/env python3
"""
Supabase client for March Madness Agent Swarm.
Handles all database writes to mm_* tables.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_client = None


def get_client():
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key or "xxxxx" in key:
        return None

    from supabase import create_client
    _client = create_client(url, key)
    return _client


def write_game_result(game_data: dict) -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.table("mm_games").upsert(game_data, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"  [supabase] mm_games write failed: {e}")
        return False


def write_agent_votes(votes: list[dict]) -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.table("mm_agent_votes").insert(votes).execute()
        return True
    except Exception as e:
        print(f"  [supabase] mm_agent_votes write failed: {e}")
        return False


def update_agent_accuracy(agent_name: str, correct: int, total: int) -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.table("mm_agent_accuracy").upsert(
            {"agent_name": agent_name, "correct": correct, "total": total},
            on_conflict="agent_name",
        ).execute()
        return True
    except Exception as e:
        print(f"  [supabase] mm_agent_accuracy write failed: {e}")
        return False


def write_status(status: dict):
    """Write status.json for dashboard polling."""
    status_file = Path(__file__).parent / "status.json"
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(status_file, "w") as f:
        json.dump(status, f, indent=2)
