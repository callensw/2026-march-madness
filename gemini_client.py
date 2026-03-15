#!/usr/bin/env python3
"""
Gemini API client for multi-model agent diversity.
Agents can run on Claude OR Gemini to get model-level disagreement.
"""

import json
import os
import random
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"


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

    url = f"{GEMINI_API_URL}/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_message}"}]}
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 512,
        },
    }

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
                import asyncio
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()

            # Extract text from Gemini response
            text = ""
            candidates = body.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    text += part.get("text", "")

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
                import asyncio
                wait = (2 ** attempt) + random.random()
                await asyncio.sleep(wait)
                continue
            raise
        except Exception as e:
            last_error = str(e)
            import asyncio
            await asyncio.sleep((2 ** attempt) + random.random())

    raise RuntimeError(f"Gemini API call failed after 3 attempts: {last_error}")


def is_gemini_available() -> bool:
    """Check if Gemini API key is configured."""
    key = os.getenv("GEMINI_API_KEY", "")
    return bool(key) and "xxxxx" not in key
