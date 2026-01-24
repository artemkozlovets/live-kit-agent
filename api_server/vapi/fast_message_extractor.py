"""Fast (non-LLM) message extraction helpers for `get_case_status`.

Big picture:
- The `get_case_status` tool runs in the critical path of the voice loop.
- Any network calls inside it (Gemini/DB/etc.) can push latency above ~500ms and
  cause the assistant to generate filler speech while it waits.

This module provides a best-effort, pure-Python extractor that is:
- deterministic
- fast (no network)
- safe to call on every tool invocation

It intentionally only extracts fields that look explicitly stated in the message.
"""

from __future__ import annotations

import re
from typing import Any, Optional


_PHONE_RE = re.compile(
    r"(?P<phone>(?:\+?1[\s\-\.]*)?(?:\(\s*\d{3}\s*\)|\d{3})[\s\-\.]*\d{3}[\s\-\.]*\d{4})"
)
_VIN_RE = re.compile(r"\bVIN\b[:\s\-]*([A-HJ-NPR-Z0-9]{8,17})\b", re.IGNORECASE)
_UNIT_RE = re.compile(r"\bunit\b[:\s\-]*([A-Z0-9\-]{1,20})\b", re.IGNORECASE)

_LAST_NAME_RE = re.compile(r"\blast name is\s+([A-Za-z][A-Za-z'\-]{1,40})\b", re.IGNORECASE)
_FIRST_NAME_RE = re.compile(r"\bfirst name is\s+([A-Za-z][A-Za-z'\-]{1,40})\b", re.IGNORECASE)
_MY_NAME_IS_RE = re.compile(
    r"\bmy name is\s+([A-Za-z][A-Za-z'\-]{1,40})(?:\s+([A-Za-z][A-Za-z'\-]{1,40}))?\b",
    re.IGNORECASE,
)

_LOCATION_RE = re.compile(
    r"\b(?:i(?:'| a)?m|im)\s+at\s+(.{3,120}?)(?:[\,\.\;\!\?]|$)",
    re.IGNORECASE,
)


def _normalize_optional_str(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _extract_phone(message: str) -> Optional[str]:
    match = _PHONE_RE.search(message)
    if not match:
        return None
    return _normalize_optional_str(match.group("phone"))


def _extract_vin(message: str) -> Optional[str]:
    match = _VIN_RE.search(message)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_unit_number(message: str) -> Optional[str]:
    match = _UNIT_RE.search(message)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_names(message: str) -> tuple[Optional[str], Optional[str]]:
    last_name = None
    first_name = None

    match = _LAST_NAME_RE.search(message)
    if match:
        last_name = _normalize_optional_str(match.group(1))

    match = _FIRST_NAME_RE.search(message)
    if match:
        first_name = _normalize_optional_str(match.group(1))

    match = _MY_NAME_IS_RE.search(message)
    if match:
        maybe_first = _normalize_optional_str(match.group(1))
        maybe_last = _normalize_optional_str(match.group(2))
        # Reason: Keep "explicit statement" bias; only fill missing fields.
        first_name = first_name or maybe_first
        last_name = last_name or maybe_last

    return first_name, last_name


def _extract_location(message: str) -> Optional[str]:
    match = _LOCATION_RE.search(message)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_complaint(message: str) -> Optional[str]:
    lowered = message.lower()
    # Reason: Keep this intentionally small and explicit; it's used mainly to
    # avoid an extra LLM round-trip for obvious cases.
    if "flat tire" in lowered:
        return "flat tire"
    if "tire" in lowered and "flat" in lowered:
        return "flat tire"
    if "dead battery" in lowered:
        return "dead battery"
    if "tow" in lowered or "towed" in lowered:
        return "tow"
    return None


def extract_customer_service_info_fast(last_user_message: str) -> dict[str, Any] | None:
    """Best-effort extraction without network calls."""
    if not isinstance(last_user_message, str) or len(last_user_message.strip()) < 2:
        return None

    first_name, last_name = _extract_names(last_user_message)
    phone = _extract_phone(last_user_message)
    location = _extract_location(last_user_message)
    complaint = _extract_complaint(last_user_message)
    unit_number = _extract_unit_number(last_user_message)
    vin = _extract_vin(last_user_message)

    any_found = any((first_name, last_name, phone, location, complaint, unit_number, vin))
    if not any_found:
        return None

    return {
        "customer": {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "company": None,
        },
        "service": {
            "location": location,
            "complaint": complaint,
            "unit_number": unit_number,
            "vin": vin,
            "vehicle_description": None,
        },
    }

