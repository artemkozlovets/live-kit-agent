"""Gemini-backed message classification for `get_case_status`.

Design goals:
- No import-time side effects (safe to import without GOOGLE_API_KEY).
- Never blocks callers with hard failures (safe fallback to NORMAL).
- Tests run without network/API keys (heuristic fallback).
"""

from __future__ import annotations

import os
import re
from enum import Enum
from typing import Any

import httpx


class MessageCategory(Enum):
    FRUSTRATED = "frustrated"
    CORRECTION = "correction"
    NEW_REQUEST = "new_request"
    CONFIRMATION = "confirmation"
    DECLINE = "decline"
    NORMAL = "normal"


CLASSIFICATION_PROMPT = """Classify this customer service message into exactly ONE category:

FRUSTRATED - User sounds impatient or is checking if anyone is there
  Examples: "Hello?", "Are you there?", "Anyone listening?", "Hellooo?"

CORRECTION - User is fixing or changing information they gave earlier
  Examples: "Actually my name is Robert", "Wrong number, it's 555-1234", "I meant Pine Street not Oak"

NEW_REQUEST - User is adding something new (additional service, new info unprompted)
  Examples: "I also need an oil change", "Oh and another truck needs help too"

CONFIRMATION - User is agreeing or confirming something
  Examples: "Yes", "That's correct", "Sounds good", "Yep that's right"

DECLINE - User is refusing or saying no to something
  Examples: "No thanks", "I don't need that", "No", "Skip that"

NORMAL - Everything else (answering questions, providing requested info, general statements)
  Examples: "My name is John", "Flat tire at 123 Main St", "The VIN is ABC123"

Message to classify: "{message}"

Reply with ONLY the category name in caps (FRUSTRATED, CORRECTION, NEW_REQUEST, CONFIRMATION, DECLINE, or NORMAL). Nothing else."""


_FRUSTRATED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*hello+\s*\??\s*$", re.IGNORECASE),
    re.compile(r"^\s*hell+o+\s*\??\s*$", re.IGNORECASE),
    re.compile(r"\bare you (still )?there\b", re.IGNORECASE),
    re.compile(r"\banyone (there|listening)\b", re.IGNORECASE),
    re.compile(r"\byou there\b", re.IGNORECASE),
)


def _get_gemini_api_key() -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_GUARD_API_KEY")
    return api_key.strip() if isinstance(api_key, str) and api_key.strip() else None


def _get_classifier_model_name() -> str:
    model = os.environ.get("GEMINI_CLASSIFIER_MODEL", "gemini-2.5-flash")
    return model.strip() or "gemini-2.5-flash"


def _category_from_text(text: str) -> MessageCategory:
    normalized = text.strip().upper() if isinstance(text, str) else ""
    category_map = {
        "FRUSTRATED": MessageCategory.FRUSTRATED,
        "CORRECTION": MessageCategory.CORRECTION,
        "NEW_REQUEST": MessageCategory.NEW_REQUEST,
        "CONFIRMATION": MessageCategory.CONFIRMATION,
        "DECLINE": MessageCategory.DECLINE,
        "NORMAL": MessageCategory.NORMAL,
    }
    return category_map.get(normalized, MessageCategory.NORMAL)


def classify_message_heuristic(message: str) -> MessageCategory:
    """Cheap, deterministic fallback classifier (used when Gemini is unavailable)."""
    if not isinstance(message, str):
        return MessageCategory.NORMAL

    normalized = message.strip().lower()
    if len(normalized) < 2:
        return MessageCategory.NORMAL

    if any(pattern.search(message) for pattern in _FRUSTRATED_PATTERNS):
        return MessageCategory.FRUSTRATED

    if normalized.startswith(("actually", "correction:", "sorry,")) or any(
        phrase in normalized for phrase in ("wrong number", "i meant", "i mean")
    ):
        return MessageCategory.CORRECTION

    if any(phrase in normalized for phrase in ("i also need", "also need", "oh and", "and another", "another truck")):
        return MessageCategory.NEW_REQUEST

    if normalized in {"yes", "yep", "yeah", "sounds good", "that's correct", "that is correct", "correct", "ok", "okay"}:
        return MessageCategory.CONFIRMATION

    if normalized in {"no", "no thanks", "no thank you", "nope", "skip that"} or any(
        phrase in normalized for phrase in ("don't need", "do not need", "no need")
    ):
        return MessageCategory.DECLINE

    return MessageCategory.NORMAL


async def _generate_gemini_text(
    *,
    prompt: str,
    api_key: str,
    model: str,
    max_output_tokens: int,
    response_mime_type: str | None = None,
    response_schema: dict[str, Any] | None = None,
) -> str | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    generation_config: dict[str, Any] = {
        "temperature": 0,
        "maxOutputTokens": max_output_tokens,
    }
    if isinstance(response_mime_type, str) and response_mime_type.strip():
        # Reason: When callers need strict JSON output, ask Gemini to emit JSON directly.
        generation_config["responseMimeType"] = response_mime_type.strip()
    if isinstance(response_schema, dict) and response_schema:
        # Reason: Optional schema tightening for structured outputs (best-effort; safe to omit).
        generation_config["responseSchema"] = response_schema

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, params={"key": api_key}, json=payload)
        response.raise_for_status()
        data: Any = response.json()

    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return None

    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        return None

    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    return text if isinstance(text, str) else None


async def classify_message(message: str) -> MessageCategory:
    """Classify a user message with Gemini, falling back safely when unavailable."""
    if not isinstance(message, str) or len(message.strip()) < 2:
        return MessageCategory.NORMAL

    api_key = _get_gemini_api_key()
    if api_key is None:
        return classify_message_heuristic(message)

    try:
        response_text = await _generate_gemini_text(
            prompt=CLASSIFICATION_PROMPT.format(message=message),
            api_key=api_key,
            model=_get_classifier_model_name(),
            max_output_tokens=10,
        )
        if response_text is None:
            return MessageCategory.NORMAL
        return _category_from_text(response_text)
    except Exception:
        # Reason: Classification should never break the call flow.
        return MessageCategory.NORMAL
