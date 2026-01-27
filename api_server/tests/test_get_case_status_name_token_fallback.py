"""get_case_status: fallback name capture for 1-word replies.

Big picture:
- In voice flows, users often answer prompts with a single word (e.g. "John").
- Gemini extraction may (correctly) refuse to guess without context, so we add a
  tiny deterministic fallback when we're in customer intake.
"""

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def _post_get_case_status(test_client: TestClient, *, call_id: str, last_user_message: str) -> dict:
    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-get-case-status",
                    "function": {
                        "name": "get_case_status",
                        "arguments": json.dumps(
                            {
                                "call_id": call_id,
                                "last_user_message": last_user_message,
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
    return json.loads(response_data["results"][0]["result"])


def test_get_case_status_single_name_sets_first_name_and_prompts_for_last(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-name-token-first"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(test_client, call_id=call_id, last_user_message="John")

        assert parsed_result["message_category"] == "normal"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Thanks. What's your last name?"

        stored = session_store.get(call_id)
        assert stored.get("first_name") == "John"
        assert stored.get("last_name") is None
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_single_name_sets_last_name_when_first_known(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-name-token-last"
    session_store.set(call_id, {"first_name": "John"})

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(test_client, call_id=call_id, last_user_message="Smith")

        assert parsed_result["message_category"] == "normal"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Thanks. What's the best phone number to reach you?"

        stored = session_store.get(call_id)
        assert stored.get("first_name") == "John"
        assert stored.get("last_name") == "Smith"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_does_not_treat_hello_as_name(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-name-token-hello"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(test_client, call_id=call_id, last_user_message="Hello?")

        assert parsed_result["message_category"] == "frustrated"
        assert parsed_result["immediate_message"] == "I'm here! Sorry about that."

        stored = session_store.get(call_id)
        assert stored == {}
    finally:
        app.dependency_overrides.pop(get_database_client, None)
