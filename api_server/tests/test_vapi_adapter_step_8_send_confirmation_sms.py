"""TDD Step 8: send_confirmation_sms returns a stable 'not configured' response."""

import json

from fastapi.testclient import TestClient


def test_send_confirmation_sms_returns_not_configured_stub() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-send-confirmation-sms"},
            "toolCallList": [
                {
                    "id": "tool-call-send-confirmation-sms",
                    "function": {
                        "name": "send_confirmation_sms",
                        "arguments": json.dumps(
                            {"phone_number": "+15551234567", "message": "Thanks, you're booked!"}
                        ),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

    # Assert
    assert response.status_code == 200
    response_data = response.json()
    parsed_result = json.loads(response_data["results"][0]["result"])

    assert parsed_result == {
        "sent": False,
        "sms_status": "not_configured",
        "next_action": "SMS skipped (not configured). Thank the caller, confirm help is on the way, and end the call politely.",
    }

