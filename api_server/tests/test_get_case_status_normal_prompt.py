"""Normal-category prompt behavior when info is missing."""

import json
import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def _post_get_case_status(test_client: TestClient, *, call_id: str, last_user_message: str) -> dict:
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    payload = {
        "call": {"id": call_id},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status",
                "name": "get_case_status",
                "arguments": {"last_user_message": last_user_message, "expected_field": None},
            }
        ],
    }

    response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
    assert response.status_code == 200
    response_data = response.json()
    return response_data["results"][0]["result"]


def test_get_case_status_normal_missing_name_prompts_for_name(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-normal-missing-name"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client,
            call_id=call_id,
            last_user_message="I have a flat tire.",
        )

        assert parsed_result["message_category"] == "normal"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Thanks. What's your name?"
        assert parsed_result["then_action"] == ""
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_normal_missing_phone_prompts_for_phone(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-normal-missing-phone"
    session_store.set(
        call_id,
        {
            "first_name": "Pat",
            "last_name": "Lee",
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client,
            call_id=call_id,
            last_user_message="I have a flat tire.",
        )

        assert parsed_result["message_category"] == "normal"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Thanks. What's the best phone number to reach you?"
        assert parsed_result["then_action"] == ""
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_normal_with_complete_service_keeps_tool_action(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-normal-ready-for-add-service"
    session_store.set(
        call_id,
        {
            "first_name": "Pat",
            "last_name": "Lee",
            "phone_number": "+15551230000",
            "service_location": "123 Main St",
            "service_complaint": "Flat tire",
            "vin_number": "1HGBH41JXMN109186",
            "services": [],
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client,
            call_id=call_id,
            last_user_message="I have a flat tire.",
        )

        assert parsed_result["message_category"] == "normal"
        assert parsed_result["response_mode"] == "tool_first"
        assert parsed_result["immediate_message"] is None
        assert parsed_result["then_action"] == (
            "Service details collected. Call add_service to save this service in the session."
        )
    finally:
        app.dependency_overrides.pop(get_database_client, None)
