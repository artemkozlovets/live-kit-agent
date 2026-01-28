"""get_case_status: expected_field persists plain answers in slot-filling mode."""

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


def test_get_case_status_expected_field_city_persists_plain_answer(monkeypatch) -> None:
    monkeypatch.setenv("GET_CASE_STATUS_SLOT_FILLING", "1")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-expected-field-city"
    session_store.clear(call_id)
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-get-case-status-expected-field-city",
                    "name": "get_case_status",
                    "arguments": {
                        "last_user_message": "Dallas",
                        "expected_field": "city",
                    },
                }
            ],
        }

        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert response.status_code == 200

        session = session_store.get(call_id)
        assert session["city"] == "Dallas"
    finally:
        app.dependency_overrides.pop(get_database_client, None)
