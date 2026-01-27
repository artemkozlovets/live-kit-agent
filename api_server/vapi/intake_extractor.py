"""Fast (non-LLM) intake extraction for "info dump" messages.

This is intentionally separate from `fast_message_extractor.py` to avoid changing
the legacy extractor contract (tests + behavior), while enabling a richer
"slot-filling with guardrails" mode.

Design goals:
- deterministic + fast (no network)
- best-effort, but conservative (avoid false positives that block re-asking)
- returns only fields that look explicitly stated
"""

from __future__ import annotations

import re
from typing import Any, Optional


_PHONE_RE = re.compile(
    r"(?P<phone>(?:\+?1[\s\-\.]*)?(?:\(\s*\d{3}\s*\)|\d{3})[\s\-\.]*\d{3}[\s\-\.]*\d{4})"
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_SPOKEN_DIGIT_RE = re.compile(r"[a-zA-Z]+")
_SPOKEN_DIGITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_VIN_RE = re.compile(r"\bVIN\b[:\s\-]*([A-HJ-NPR-Z0-9]{8,17})\b", re.IGNORECASE)
_UNIT_RE = re.compile(r"\bunit\b[:\s\-]*([A-Z0-9\-]{1,20})\b", re.IGNORECASE)

_LAST_NAME_RE = re.compile(r"\blast name is\s+([A-Za-z][A-Za-z'\-]{1,40})\b", re.IGNORECASE)
_FIRST_NAME_RE = re.compile(r"\bfirst name is\s+([A-Za-z][A-Za-z'\-]{1,40})\b", re.IGNORECASE)
_MY_NAME_IS_RE = re.compile(
    r"\bmy name is\s+([A-Za-z][A-Za-z'\-]{1,40})(?:\s+([A-Za-z][A-Za-z'\-]{1,40}))?\b",
    re.IGNORECASE,
)

_COMPANY_RE = re.compile(
    r"\b(?:my\s+company\s+is|company\s+is|i\s+work\s+for|i'?m\s+with)\s+(.{2,80}?)(?:[\,\.\;\!\?]|$)",
    re.IGNORECASE,
)

_ADDRESS_RE = re.compile(
    r"\b(?:my\s+address\s+is|address\s+is)\s+"
    r"(?P<street>\d{1,6}\s+[^,\n]{3,80})"
    r"(?:,\s*(?P<city>[A-Za-z .'\-]{2,40})\s+(?P<state>[A-Za-z]{2})\s*(?P<zip>\d{5})(?:-\d{4})?)?"
    r"(?:[\,\.\;\!\?]|$)",
    re.IGNORECASE,
)

_LOCATION_RE = re.compile(
    r"\b(?:i(?:'| a)?m|im)\s+at\s+(.{3,120}?)(?:[\,\.\;\!\?]|$)",
    re.IGNORECASE,
)

_VEHICLE_DESC_RE = re.compile(
    r"\b(?:my\s+(?:truck|car|vehicle|unit)\s+is|it'?s)\s+(?:a\s+)?(.{2,80}?)(?:[\,\.\;\!\?]|$)",
    re.IGNORECASE,
)


def _normalize_optional_str(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _extract_spoken_digits(text: str) -> Optional[str]:
    tokens = _SPOKEN_DIGIT_RE.findall(text.lower())
    digits = [(_SPOKEN_DIGITS.get(token)) for token in tokens]
    digits = [digit for digit in digits if digit is not None]
    if len(digits) < 7:
        return None
    return "".join(digits)


def _extract_phone(text: str) -> Optional[str]:
    match = _PHONE_RE.search(text)
    if match:
        return _normalize_optional_str(match.group("phone"))
    return _extract_spoken_digits(text)


def _extract_email(text: str) -> Optional[str]:
    match = _EMAIL_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(0))


def _extract_vin(text: str) -> Optional[str]:
    match = _VIN_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_unit_number(text: str) -> Optional[str]:
    match = _UNIT_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_names(text: str) -> tuple[Optional[str], Optional[str]]:
    last_name = None
    first_name = None

    match = _LAST_NAME_RE.search(text)
    if match:
        last_name = _normalize_optional_str(match.group(1))

    match = _FIRST_NAME_RE.search(text)
    if match:
        first_name = _normalize_optional_str(match.group(1))

    match = _MY_NAME_IS_RE.search(text)
    if match:
        maybe_first = _normalize_optional_str(match.group(1))
        maybe_last = _normalize_optional_str(match.group(2))
        # Reason: Keep "explicit statement" bias; only fill missing fields.
        first_name = first_name or maybe_first
        last_name = last_name or maybe_last

    return first_name, last_name


def _extract_company(text: str) -> Optional[str]:
    match = _COMPANY_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_customer_address(text: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    match = _ADDRESS_RE.search(text)
    if not match:
        return None, None, None, None

    street = _normalize_optional_str(match.group("street"))
    city = _normalize_optional_str(match.group("city"))
    state = _normalize_optional_str(match.group("state"))
    postal_code = _normalize_optional_str(match.group("zip"))
    if state is not None:
        state = state.upper()
    return street, city, state, postal_code


def _extract_location(text: str) -> Optional[str]:
    match = _LOCATION_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_vehicle_description(text: str) -> Optional[str]:
    match = _VEHICLE_DESC_RE.search(text)
    if not match:
        return None
    return _normalize_optional_str(match.group(1))


def _extract_complaint(text: str) -> Optional[str]:
    lowered = text.lower()
    if "flat tire" in lowered or ("tire" in lowered and "flat" in lowered):
        return "flat tire"
    if "dead battery" in lowered:
        return "dead battery"
    if "tow" in lowered or "towed" in lowered:
        return "tow"
    return None


def extract_intake_info_fast(last_user_message: str) -> dict[str, Any] | None:
    """Best-effort extraction for rich intake ("info dump") messages."""
    if not isinstance(last_user_message, str) or len(last_user_message.strip()) < 2:
        return None

    first_name, last_name = _extract_names(last_user_message)
    phone = _extract_phone(last_user_message)
    email_address = _extract_email(last_user_message)
    company = _extract_company(last_user_message)
    street, city, state, postal_code = _extract_customer_address(last_user_message)

    location = _extract_location(last_user_message)
    complaint = _extract_complaint(last_user_message)
    unit_number = _extract_unit_number(last_user_message)
    vin = _extract_vin(last_user_message)
    vehicle_description = _extract_vehicle_description(last_user_message)

    any_found = any(
        (
            first_name,
            last_name,
            phone,
            email_address,
            company,
            street,
            city,
            state,
            postal_code,
            location,
            complaint,
            unit_number,
            vin,
            vehicle_description,
        )
    )
    if not any_found:
        return None

    return {
        "customer": {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "company": company,
            "email_address": email_address,
            "streetAddress": street,
            "city": city,
            "state": state,
            "postalCode": postal_code,
            "customer_position": None,
            "marketing_source": None,
        },
        "service": {
            "location": location,
            "complaint": complaint,
            "unit_number": unit_number,
            "vin": vin,
            "vehicle_description": vehicle_description,
        },
    }

