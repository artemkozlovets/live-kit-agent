from __future__ import annotations

from api_server.vapi.handlers.session import handle_get_session_summary
from api_server.vapi.session_store import SessionStore


def test_get_session_summary_next_action_mentions_confirm_services() -> None:
    session_store = SessionStore()
    call_id = "call-test"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "unit_nickname": "Big Pete",
                    "service_location": "123 Main St",
                    "service_complaint": "Flat tire",
                }
            ],
            "services_confirmed": False,
        },
    )

    result = handle_get_session_summary(
        tool_call={},
        message_payload={"call": {"id": call_id}},
        session_store=session_store,
        database_client=None,  # type: ignore[arg-type]
    )

    assert "confirm_services" in str(result.get("next_action") or "")

