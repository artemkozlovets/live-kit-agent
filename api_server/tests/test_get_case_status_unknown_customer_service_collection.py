"""get_case_status should move to service collection once minimal customer info is present.

Big picture:
- For unknown customers (no customer_id), we still want to collect service info.
- A preflight callback number is treated as the customer's phone number.
"""

import json

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

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps({"call_id": call_id, "last_user_message": "Hi"}),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = client.post("/vapi/tools", json=payload)
        assert response.status_code == 200
        parsed_result = json.loads(response.json()["results"][0]["result"])

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"]["to_service_collection"] is True
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "What vehicle do you need service for?"
        assert parsed_result["then_action"] == ""
    finally:
        app.dependency_overrides.pop(get_database_client, None)
