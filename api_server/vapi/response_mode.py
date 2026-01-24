"""Message-category -> response-mode mapping for assistants.

This is pure logic: callers decide when to invoke it (e.g., only when a
`last_user_message` is provided).
"""

from __future__ import annotations

from typing import Any

from api_server.vapi.message_classifier import MessageCategory


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

    return (
        "tool_first",
        None,
        None,
    )
