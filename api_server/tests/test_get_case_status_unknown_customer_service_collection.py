"""get_case_status should move to service collection once minimal customer info is present.

Big picture:
- For unknown customers (no customer_id), we still want to collect service info.
- A preflight callback number is treated as the customer's phone number.
"""

import json
import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None

    def find_customer_by_phone_number(self, inbound_args):  # noqa: ANN001
        return None


def test_unknown_customer_with_name_and_phone_enters_service_collection(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-unknown-enters-service-collection"
    session_store.set(
        call_id,
        {
            "first_name": "John",
            "last_name": "Smith",
            "phone_number": "+15551230000",
        },
    )
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-get-case-status",
                    "name": "get_case_status",
                    "arguments": {"last_user_message": "Hi", "expected_field": None},
                }
            ],
        }

        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert response.status_code == 200
        parsed_result = response.json()["results"][0]["result"]

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"]["to_service_collection"] is True
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "What vehicle do you need service for?"
        assert parsed_result["then_action"] == ""
    finally:
        app.dependency_overrides.pop(get_database_client, None)
