"""check_customer: fall back to session-known data when tool omits known_data."""

from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_phone_number(self, inbound_args):  # noqa: ANN001
        _ = inbound_args
        return None


def _post_check_customer_tool_call(*, call_id: str, arguments: dict) -> dict:
    from api_server.server.fastapi_app import app

    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-check-customer",
                    "name": "check_customer",
                    "arguments": arguments,
                }
            ],
        }
        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
        assert response.status_code == 200
        response_data = response.json()
        return response_data["results"][0]["result"]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_check_customer_uses_session_known_data_when_known_data_omitted() -> None:
    from api_server.vapi.router import session_store

    call_id = "call-check-customer-session-known-data"
    session_store.set(
        call_id,
        {
            "first_name": "Kyle",
            "last_name": "Aduan",
            "company_name": "AFS",
            "city": "Dallas",
            "state": "TX",
        },
    )

    parsed_result = _post_check_customer_tool_call(
        call_id=call_id,
        arguments={"phone_number": "+15551234567"},
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == [
        "email_address",
        "streetAddress",
        "postalCode",
    ]


def test_check_customer_blank_known_data_falls_back_to_session() -> None:
    from api_server.vapi.router import session_store

    call_id = "call-check-customer-blank-known-data"
    session_store.set(
        call_id,
        {
            "first_name": "Kyle",
            "last_name": "Aduan",
            "company_name": "AFS",
            "city": "Dallas",
            "state": "TX",
        },
    )

    parsed_result = _post_check_customer_tool_call(
        call_id=call_id,
        arguments={
            "phone_number": "+15551234567",
            "known_data": {"city": "   "},
        },
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == [
        "email_address",
        "streetAddress",
        "postalCode",
    ]


def test_check_customer_session_known_data_ignores_non_strings() -> None:
    from api_server.vapi.router import session_store

    call_id = "call-check-customer-session-non-string"
    session_store.set(
        call_id,
        {
            "first_name": "Kyle",
            "city": 123,
        },
    )

    parsed_result = _post_check_customer_tool_call(
        call_id=call_id,
        arguments={"phone_number": "+15551234567"},
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == [
        "last_name",
        "company_name",
        "email_address",
        "streetAddress",
        "city",
        "state",
        "postalCode",
    ]
