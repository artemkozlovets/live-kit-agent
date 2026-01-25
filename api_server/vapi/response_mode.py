"""Message-category -> response-mode mapping for assistants.

This is pure logic: callers decide when to invoke it (e.g., only when a
`last_user_message` is provided).
"""

from __future__ import annotations

from typing import Any

from api_server.vapi.message_classifier import MessageCategory


def _normalize_missing_fields(case_state: dict[str, Any]) -> set[str]:
    missing_fields = case_state.get("missing_fields")
    if not isinstance(missing_fields, list):
        return set()
    normalized: set[str] = set()
    for item in missing_fields:
        if isinstance(item, str) and item.strip():
            normalized.add(item.strip())
    return normalized


def _normal_immediate_message(case_state: dict[str, Any]) -> str | None:
    missing_fields = _normalize_missing_fields(case_state)
    if not missing_fields:
        return None

    current_phase = case_state.get("current_phase")
    if current_phase == "customer_intake":
        if "first_name" in missing_fields or "last_name" in missing_fields:
            return "Thanks. What's your name?"
        if "phone" in missing_fields:
            return "Thanks. What's the best phone number to reach you?"

    if current_phase == "service_collection":
        if missing_fields.intersection({"vin", "unit_number", "unit_nickname", "vehicle_identifier"}):
            return "What vehicle do you need service for?"
        if "location" in missing_fields:
            return "Where is the vehicle located?"
        if "complaint" in missing_fields:
            return "What's the issue with the vehicle?"

    return None


def compute_response_mode(
    *,
    category: MessageCategory,
    case_state: dict[str, Any],
    last_message: str | None,
) -> tuple[str, str | None, str | None]:
    """Determine how the assistant should respond.

    Returns: (response_mode, immediate_message, then_action_override)
    """
    _ = last_message  # reserved for future rules that depend on message text

    if category == MessageCategory.FRUSTRATED:
        return (
            "speak_first",
            "I'm here! Sorry about that.",
            case_state.get("next_action") if isinstance(case_state.get("next_action"), str) else "Continue where we left off.",
        )

    if category == MessageCategory.CORRECTION:
        return (
            "update_first",
            None,
            "Apply the corrections, then say 'Got it' and continue.",
        )

    if category == MessageCategory.NEW_REQUEST:
        return (
            "speak_first",
            "Sure, I can help with that too.",
            "Ask for details about the new request.",
        )

    if category == MessageCategory.CONFIRMATION:
        return (
            "tool_first",
            None,
            "Proceed with the next step.",
        )

    if category == MessageCategory.DECLINE:
        return (
            "speak_first",
            "No problem.",
            "Skip that step and continue.",
        )

    if category == MessageCategory.NORMAL:
        immediate_message = _normal_immediate_message(case_state)
        if immediate_message is not None:
            # Reason: Avoid tool parsing when the next step is just collecting info from the caller.
            return ("speak_first", immediate_message, "")

    return (
        "tool_first",
        None,
        None,
    )
