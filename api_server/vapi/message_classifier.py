"""Deterministic message classification for `get_case_status` (no network)."""

from __future__ import annotations

import re
from enum import Enum


class MessageCategory(Enum):
    FRUSTRATED = "frustrated"
    CORRECTION = "correction"
    NEW_REQUEST = "new_request"
    CONFIRMATION = "confirmation"
    DECLINE = "decline"
    NORMAL = "normal"


_FRUSTRATED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*hello+\s*\??\s*$", re.IGNORECASE),
    re.compile(r"^\s*hell+o+\s*\??\s*$", re.IGNORECASE),
    re.compile(r"\bare you (still )?there\b", re.IGNORECASE),
    re.compile(r"\banyone (there|listening)\b", re.IGNORECASE),
    re.compile(r"\byou there\b", re.IGNORECASE),
)


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


async def classify_message(message: str) -> MessageCategory:
    """Async shim for compatibility with call sites."""
    if not isinstance(message, str) or len(message.strip()) < 2:
        return MessageCategory.NORMAL
    return classify_message_heuristic(message)
