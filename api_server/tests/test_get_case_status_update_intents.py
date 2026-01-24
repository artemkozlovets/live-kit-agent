"""get_case_status: detect explicit update intents after completion.

These tests ensure we keep session/customer data after booking completion and
can pivot into a correction flow when the caller asks to update details.
"""

import json

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, *, customers_by_id: dict[str, CustomerRecord]) -> None:
        self.customers_by_id = dict(customers_by_id)

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        return self.customers_by_id.get(customer_id)


def _post_get_case_status(*, test_client: TestClient, call_id: str, last_user_message: str) -> dict:
    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-get-case-status-update-intents",
                    "function": {
                        "name": "get_case_status",
                        "arguments": json.dumps(
                            {"call_id": call_id, "last_user_message": last_user_message}
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


def test_get_case_status_update_intent_phone_prompts_for_new_value(monkeypatch) -> None:
    # Reason: Keep tests fast + deterministic (no Gemini network).
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-update-phone"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "customer_registered": True,
            "current_phase": "completed",
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_id={
            "CUST-123": CustomerRecord(
                customer_id="CUST-123",
                customer_name="Tom Johnson",
                phone_number="+13053063078",
                email="afs@gmail.com",
                company_name="AFS",
            )
        }
    )
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            last_user_message="I want to update my phone number",
        )

        assert parsed_result["customer"]["id"] == "CUST-123"
        assert parsed_result["current_phase"] == "correction"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Sure, what's your new phone number?"
        assert "update_customer" in parsed_result["then_action"]
        assert "phone_number" in parsed_result["then_action"]
        assert "CUST-123" in parsed_result["then_action"]
        assert parsed_result["detected_corrections"] == {
            "field": "phone_number",
            "customer_id": "CUST-123",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_update_intent_email_prompts_for_new_value(monkeypatch) -> None:
    # Reason: Keep tests fast + deterministic (no Gemini network).
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-update-email"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "customer_registered": True,
            "current_phase": "completed",
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(
        customers_by_id={
            "CUST-123": CustomerRecord(
                customer_id="CUST-123",
                customer_name="Tom Johnson",
                phone_number="+13053063078",
                email="afs@gmail.com",
                company_name="AFS",
            )
        }
    )
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            last_user_message="Can you change my email?",
        )

        assert parsed_result["customer"]["id"] == "CUST-123"
        assert parsed_result["current_phase"] == "correction"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Sure, what's your new email address?"
        assert parsed_result["detected_corrections"]["field"] == "email_address"
        assert parsed_result["detected_corrections"]["customer_id"] == "CUST-123"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_update_intent_without_customer_does_not_trigger(monkeypatch) -> None:
    # Reason: Keep tests fast + deterministic (no Gemini network).
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-update-no-customer"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(customers_by_id={})
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            last_user_message="I want to update my phone number",
        )

        assert parsed_result["current_phase"] != "correction"
    finally:
        app.dependency_overrides.pop(get_database_client, None)

