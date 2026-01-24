"""check_customer: backend computes missing fields from known_data.

This locks in the "smart tool" pattern: the assistant passes all customer
data collected so far so the backend can return only what's still missing.
"""

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_phone_number(self, inbound_args):
        _ = inbound_args
        return None


def _post_check_customer_tool_call(*, call_id: str, arguments: dict) -> dict:
    from api_server.server.fastapi_app import app

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-check-customer",
                        "function": {
                            "name": "check_customer",
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }
        response = client.post("/vapi/tools", json=payload)
        assert response.status_code == 200
        response_data = response.json()
        return json.loads(response_data["results"][0]["result"])
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_check_customer_missing_customer_with_partial_known_data_returns_only_missing_fields() -> None:
    parsed_result = _post_check_customer_tool_call(
        call_id="call-known-data-partial",
        arguments={
            "phone_number": "+15551234567",
            "known_data": {
                "first_name": "Kyle",
                "company_name": "AFS",
                "city": "Dallas",
            },
        },
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == [
        "last_name",
        "email_address",
        "streetAddress",
        "state",
        "postalCode",
    ]


def test_check_customer_known_data_treats_blank_strings_as_missing() -> None:
    parsed_result = _post_check_customer_tool_call(
        call_id="call-known-data-blank-strings",
        arguments={
            "phone_number": "+15551234567",
            "known_data": {
                "first_name": "Kyle",
                "last_name": "   ",
                "company_name": "AFS",
                "email_address": "",
                "streetAddress": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postalCode": "75201",
            },
        },
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == ["last_name", "email_address"]


def test_check_customer_known_data_ignores_invalid_known_data_shape() -> None:
    parsed_result = _post_check_customer_tool_call(
        call_id="call-known-data-invalid-shape",
        arguments={
            "phone_number": "+15551234567",
            "known_data": "not-an-object",
        },
    )

    assert parsed_result["found"] is False
    assert parsed_result["next_action_fields"] == [
        "first_name",
        "last_name",
        "company_name",
        "email_address",
        "streetAddress",
        "city",
        "state",
        "postalCode",
    ]


def test_check_customer_known_data_complete_returns_ready_to_register() -> None:
    parsed_result = _post_check_customer_tool_call(
        call_id="call-known-data-complete",
        arguments={
            "phone_number": "+15551234567",
            "known_data": {
                "first_name": "Kyle",
                "last_name": "Aduan",
                "company_name": "AFS",
                "email_address": "kyle@afs.com",
                "streetAddress": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postalCode": "75201",
            },
        },
    )

    assert parsed_result == {
        "found": False,
        "ready_to_register": True,
        "next_action_fields": [],
        "next_action": (
            "No customer found, but all required customer fields are already collected. "
            "Immediately call register_new_customer now."
        ),
    }

