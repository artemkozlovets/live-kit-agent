"""get_case_status: slot-filling extraction overwrites explicit fields."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None

    def find_customer_by_phone_number(self, inbound_args):  # noqa: ANN001
        return None


def test_get_case_status_slot_filling_overwrites_email(monkeypatch) -> None:
    monkeypatch.setenv("GET_CASE_STATUS_SLOT_FILLING", "1")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-slot-filling-overwrite-email"
    session_store.set(call_id, {"email_address": "old@example.com"})

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-slot-overwrite-email",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "My email is new@example.com.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = client.post("/vapi/tools", json=payload)
        assert response.status_code == 200

        session = session_store.get(call_id)
        assert session["email_address"] == "new@example.com"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_slot_filling_overwrites_service_location(monkeypatch) -> None:
    monkeypatch.setenv("GET_CASE_STATUS_SLOT_FILLING", "1")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-slot-filling-overwrite-location"
    session_store.set(call_id, {"service_location": "Old Location"})

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-slot-overwrite-location",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "I'm at 7th Street.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = client.post("/vapi/tools", json=payload)
        assert response.status_code == 200

        session = session_store.get(call_id)
        assert session["service_location"] == "7th Street"
    finally:
        app.dependency_overrides.pop(get_database_client, None)

