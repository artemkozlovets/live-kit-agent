"""get_case_status: message-aware behavior fields.

These tests cover the *additional* fields returned when callers pass
`last_user_message`. Existing tests assert the legacy shape when that value
is omitted.
"""

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def test_get_case_status_with_last_user_message_includes_response_mode(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-with-message"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-with-message",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "Hello?",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

        assert response.status_code == 200
        response_data = response.json()
        parsed_result = json.loads(response_data["results"][0]["result"])

        assert parsed_result["message_category"] == "frustrated"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "I'm here! Sorry about that."
        assert parsed_result["then_action"] == parsed_result["next_action"]
        assert "detected_corrections" in parsed_result
    finally:
        app.dependency_overrides.pop(get_database_client, None)
