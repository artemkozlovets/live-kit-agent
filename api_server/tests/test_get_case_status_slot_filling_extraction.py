"""get_case_status: slot-filling mode persists extended intake fields."""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None

    def find_customer_by_phone_number(self, inbound_args):  # noqa: ANN001
        return None


def test_get_case_status_slot_filling_persists_extended_customer_fields(monkeypatch) -> None:
    monkeypatch.setenv("GET_CASE_STATUS_SLOT_FILLING", "1")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-slot-filling-extracts-extended-customer-fields"
    session_store.clear(call_id)
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-get-case-status-slot-filling",
                    "name": "get_case_status",
                    "arguments": {
                        "last_user_message": (
                            "My name is John Johnson. "
                            "My phone number is three zero five three one seven nine eight four zero. "
                            "My email is john@example.com. "
                            "My address is 123 Main St, Dallas TX 75201."
                        ),
                        "expected_field": None,
                    },
                }
            ],
        }

        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert response.status_code == 200

        session = session_store.get(call_id)
        assert session["first_name"] == "John"
        assert session["last_name"] == "Johnson"
        assert session["phone_number"] == "3053179840"
        assert session["email_address"] == "john@example.com"
        assert session["streetAddress"] == "123 Main St"
        assert session["city"] == "Dallas"
        assert session["state"] == "TX"
        assert session["postalCode"] == "75201"
    finally:
        app.dependency_overrides.pop(get_database_client, None)
