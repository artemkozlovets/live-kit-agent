"""get_case_status: slot-filling mode includes customer_known_data."""

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


def test_get_case_status_slot_filling_includes_customer_known_data(monkeypatch) -> None:
    monkeypatch.setenv("GET_CASE_STATUS_SLOT_FILLING", "1")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-slot-filling-known-data"
    session_store.set(
        call_id,
        {
            "first_name": "Kyle",
            "last_name": "Aduan",
            "company_name": "AFS",
            "email_address": "kyle@afs.com",
            "streetAddress": "123 Main St",
            "city": "Dallas",
            "state": "TX",
            "postalCode": "75201",
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
                    "id": "tool-call-get-case-status-slot-filling-known-data",
                    "name": "get_case_status",
                    "arguments": {"last_user_message": "Hi", "expected_field": None},
                }
            ],
        }

        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert response.status_code == 200
        parsed_result = response.json()["results"][0]["result"]

        assert parsed_result["customer_known_data"] == {
            "first_name": "Kyle",
            "last_name": "Aduan",
            "company_name": "AFS",
            "email_address": "kyle@afs.com",
            "phone_number": None,
            "customer_position": None,
            "marketing_source": None,
            "streetAddress": "123 Main St",
            "city": "Dallas",
            "state": "TX",
            "country": None,
            "postalCode": "75201",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)
