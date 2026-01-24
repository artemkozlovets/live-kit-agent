"""Explicit update-intent detection for post-booking corrections.

Big picture:
- After an order is completed, callers often ask to *change* an already-known
  detail ("update my phone number").
- We want a deterministic, fast, no-network way to detect these intents so the
  assistant can pivot into a correction flow without losing session context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerUpdateIntent:
    field: str
    friendly_field: str


_UPDATE_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bupdate\s+(?:my\s+)?(phone|number|email|address|name)\b", re.IGNORECASE),
    re.compile(r"\bchange\s+(?:my\s+)?(phone|number|email|address|name)\b", re.IGNORECASE),
    re.compile(r"\bcorrect\s+(?:my\s+)?(phone|number|email|address|name)\b", re.IGNORECASE),
    re.compile(r"\bwrong\s+(phone|number|email|address|name)\b", re.IGNORECASE),
    re.compile(r"\bactually\b.*\b(phone|number|email|address|name)\b.*\b(is|should be)\b", re.IGNORECASE),
)

_PHONE_FIELD_PATTERN = re.compile(r"\b(phone|phone number|number)\b", re.IGNORECASE)
_EMAIL_FIELD_PATTERN = re.compile(r"\b(e-?mail|email)\b", re.IGNORECASE)
_ADDRESS_FIELD_PATTERN = re.compile(r"\b(address|street|zip|postal|city|state)\b", re.IGNORECASE)
_NAME_FIELD_PATTERN = re.compile(r"\bname\b", re.IGNORECASE)


def detect_customer_update_intent(message: str) -> CustomerUpdateIntent | None:
    if not isinstance(message, str) or len(message.strip()) < 2:
        return None

    if not any(pattern.search(message) for pattern in _UPDATE_INTENT_PATTERNS):
        return None

    if _PHONE_FIELD_PATTERN.search(message):
        return CustomerUpdateIntent(field="phone_number", friendly_field="phone number")
    if _EMAIL_FIELD_PATTERN.search(message):
        return CustomerUpdateIntent(field="email_address", friendly_field="email address")
    if _ADDRESS_FIELD_PATTERN.search(message):
        # Reason: update_customer expects address fields (streetAddress/city/state/postalCode).
        # We treat this as a single "address" intent to drive a short clarification turn.
        return CustomerUpdateIntent(field="streetAddress", friendly_field="address")
    if _NAME_FIELD_PATTERN.search(message):
        # Reason: update_customer maps name updates through contact_name.
        return CustomerUpdateIntent(field="contact_name", friendly_field="name")

    return None

