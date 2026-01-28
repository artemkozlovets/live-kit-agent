"""TDD Step 8: send_confirmation_sms returns a stable 'not configured' response."""

import os

from fastapi.testclient import TestClient


def test_send_confirmation_sms_returns_not_configured_stub() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)
    token = "test-secret"
    previous_token = os.environ.get("TOOLS_TOKEN")
    os.environ["TOOLS_TOKEN"] = token

    vapi_tool_call_payload = {
        "call": {"id": "call-send-confirmation-sms"},
        "tool_calls": [
            {
                "id": "tool-call-send-confirmation-sms",
                "name": "send_confirmation_sms",
                "arguments": {"phone_number": "+15551234567", "message": "Thanks, you're booked!"},
            }
        ],
    }

    try:
        # Act
        response = test_client.post("/tools", json=vapi_tool_call_payload, headers={"X-TOOLS-TOKEN": token})

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["results"][0]["ok"] is True
        parsed_result = response_data["results"][0]["result"]

        assert parsed_result == {
            "sent": False,
            "sms_status": "not_configured",
            "next_action": "SMS skipped (not configured). Thank the caller, confirm help is on the way, and end the call politely.",
        }
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token
