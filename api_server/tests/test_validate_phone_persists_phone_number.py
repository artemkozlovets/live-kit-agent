"""validate_phone should persist the normalized phone number in session.

Big picture:
- The LiveKit agent collects a callback number during preflight.
- Later, get_case_status shouldn't re-ask for the same phone number.
"""

import json
import os

from fastapi.testclient import TestClient


def test_validate_phone_valid_stores_phone_number_in_session() -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-validate-phone-persists"
    session_store.clear(call_id)
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    client = TestClient(app)
    payload = {
        "call": {"id": call_id},
        "tool_calls": [
            {
                "id": "tool-call-validate-phone",
                "name": "validate_phone",
                "arguments": {"phone_number": "305-317-9840"},
            }
        ],
    }

    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
    assert response.status_code == 200

    stored = session_store.get(call_id)
    assert stored.get("phone_number") == "+13053179840"
