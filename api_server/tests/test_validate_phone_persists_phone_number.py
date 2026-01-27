"""validate_phone should persist the normalized phone number in session.

Big picture:
- The LiveKit agent collects a callback number during preflight.
- Later, get_case_status shouldn't re-ask for the same phone number.
"""

import json

from fastapi.testclient import TestClient


def test_validate_phone_valid_stores_phone_number_in_session() -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-validate-phone-persists"
    session_store.clear(call_id)

    client = TestClient(app)
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-validate-phone",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "305-317-9840"}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    response = client.post("/vapi/tools", json=payload)
    assert response.status_code == 200

    stored = session_store.get(call_id)
    assert stored.get("phone_number") == "+13053179840"
