#!/usr/bin/env python3
"""
Gemini API client for multi-model agent diversity.
Agents can run on Claude OR Gemini to get model-level disagreement.
"""

import asyncio
import json
import logging
import os
import random
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger("swarm")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"


def _sanitize_url(url: str) -> str:
    """Remove API key from URL for safe logging."""
    return re.sub(r'key=[^&]+', 'key=***REDACTED***', url)


async def call_gemini_api(
    client: httpx.AsyncClient,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.5,
    timeout: float = 45.0,
    semaphore=None,
) -> tuple[str, int, int]:
    """
    Call Gemini API. Returns (response_text, input_tokens, output_tokens).
    Retries up to 3 times with exponential backoff.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    # NOTE: Google's Gemini API requires the key as a query parameter;
    # header-based auth is not supported on the free tier.
    # Use _sanitize_url() when logging to avoid exposing the key.
    url = f"{GEMINI_API_URL}/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_message}"}]}
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    # For thinking models (2.5), disable thinking to avoid token budget issues
    if "2.5" in model:
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

    last_error = None
    for attempt in range(3):
        try:
            if semaphore:
                async with semaphore:
                    resp = await client.post(url, json=payload, timeout=timeout)
            else:
                resp = await client.post(url, json=payload, timeout=timeout)

            if resp.status_code == 429:
                wait = (2 ** attempt) + random.random()
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()

            # Extract text from Gemini response
            text = ""
            candidates = body.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    text += part.get("text", "")

                # Log finish reason for debugging
                finish_reason = candidate.get("finishReason", "UNKNOWN")
                if finish_reason in ("SAFETY", "BLOCKED"):
                    log.error(
                        f"  Gemini response blocked (finishReason={finish_reason}) "
                        f"for URL {_sanitize_url(url)} (attempt {attempt+1})"
                    )
                    raise RuntimeError(
                        f"Gemini content blocked: finishReason={finish_reason}"
                    )
                if finish_reason not in ("STOP", "UNKNOWN"):
                    log.warning(f"  Gemini finishReason: {finish_reason} (attempt {attempt+1})")
                    if finish_reason == "MAX_TOKENS" and attempt < 2:
                        # Retry with more tokens
                        await asyncio.sleep(0.5)
                        continue

            # Token usage
            usage = body.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount", 0)
            output_tokens = usage.get("candidatesTokenCount", 0)

            return text, input_tokens, output_tokens

        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}"
            if e.response.status_code >= 500:
                wait = (2 ** attempt) + random.random()
                await asyncio.sleep(wait)
                continue
            raise
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep((2 ** attempt) + random.random())

    raise RuntimeError(f"Gemini API call failed after 3 attempts: {last_error}")


def is_gemini_available() -> bool:
    """Check if Gemini API key is configured."""
    key = os.getenv("GEMINI_API_KEY", "")
    return bool(key) and "xxxxx" not in key
