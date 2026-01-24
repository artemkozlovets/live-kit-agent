"""In-memory Vapi session store keyed by call_id.

This store holds call-scoped state needed for multi-step Vapi tool flows, such as:
- attempt counters (phone_attempts, vin_attempts)
- collected services list (for multi-service orders)
- derived identifiers like customer_id (so Booking doesn't rely on extractedVariables)

MVP constraint: we run a single instance, so in-memory storage is acceptable.
"""

from __future__ import annotations

from typing import Any


class SessionStore:
    """Dict-backed session store keyed by call_id."""

    def __init__(self) -> None:
        self._session_by_call_id: dict[str, dict[str, Any]] = {}

    def get(self, call_id: str) -> dict[str, Any]:
        """Return a copy of the session dict for call_id (or empty dict)."""
        return dict(self._session_by_call_id.get(call_id, {}))

    def set(self, call_id: str, session: dict[str, Any]) -> None:
        """Replace the session dict for call_id."""
        self._session_by_call_id[call_id] = dict(session)

    def clear(self, call_id: str) -> None:
        """Remove session data for call_id."""
        self._session_by_call_id.pop(call_id, None)

