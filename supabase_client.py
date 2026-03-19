#!/usr/bin/env python3
"""
Supabase client for March Madness Agent Swarm.
Handles all database writes to mm_* tables.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()

# Timeout (seconds) applied to the underlying httpx transport used by supabase-py.
_TIMEOUT_SECONDS = 30


def get_client():
    global _client
    # Fast path: already initialised (no lock needed for the read).
    if _client is not None:
        return _client

    with _client_lock:
        # Double-checked locking: another thread may have initialised while we waited.
        if _client is not None:
            return _client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")

        if not url or not key or "xxxxx" in key:
            return None

        try:
            from supabase import create_client, ClientOptions
            import httpx

            # supabase-py >= 2.x accepts a ClientOptions with a custom
            # httpx client, which lets us enforce a connect/read timeout.
            timeout = httpx.Timeout(_TIMEOUT_SECONDS, connect=10)
            options = ClientOptions(
                postgrest_client_timeout=_TIMEOUT_SECONDS,
            )
            _client = create_client(url, key, options=options)

            # Additionally patch the underlying httpx timeout on the postgrest
            # client if the attribute is accessible (works with supabase-py >=2).
            try:
                _client.postgrest.session.timeout = timeout  # type: ignore[union-attr]
            except AttributeError:
                log.info(
                    "Could not patch postgrest session timeout; "
                    "the library version may not expose this attribute."
                )
        except TypeError:
            # Older supabase-py versions may not accept ClientOptions –
            # fall back to the basic constructor.
            from supabase import create_client

            log.info(
                "supabase-py does not support ClientOptions; "
                "creating client without explicit timeout configuration."
            )
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
        log.error("mm_games write failed: %s", e)
        return False


def write_agent_votes(votes: list[dict]) -> bool:
    client = get_client()
    if not client:
        return False
    try:
        client.table("mm_agent_votes").upsert(
            votes, on_conflict="game_id,agent_name,round_number"
        ).execute()
        return True
    except Exception as e:
        log.error("mm_agent_votes write failed: %s", e)
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
        log.error("mm_agent_accuracy write failed: %s", e)
        return False


def write_status(status: dict):
    """Write status.json for dashboard polling (atomic via rename)."""
    status_file = Path(__file__).parent / "status.json"
    status["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Write to a temp file in the same directory, then atomically rename.
    # Using the same directory ensures we stay on the same filesystem,
    # which is required for os.rename() to be atomic on POSIX.
    dir_ = status_file.parent
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(status, f, indent=2)
            os.rename(tmp_path, status_file)
        except BaseException:
            # Clean up the temp file on any failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        log.error("Failed to write status.json: %s", e)
