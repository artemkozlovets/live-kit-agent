"""get_case_status: extract + persist last_user_message fields.

These tests validate that when callers pass `last_user_message`, we can extract
customer/service info, persist it into storage, and compute `missing_fields`
from the updated state.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def test_get_case_status_extracts_message_fields_and_updates_missing_fields(
    monkeypatch,
) -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    call_id = "call-get-case-status-extract-message-fields"
    session_store.clear(call_id)

    async def fake_extractor(message: str):  # noqa: ANN001
        assert isinstance(message, str)
        return {
            "customer": {
                "first_name": None,
                "last_name": "Johnson",
                "phone": None,
                "company": None,
            },
            "service": {
                "location": "6th Street",
                "complaint": "Flat tire",
                "unit_number": None,
                "vin": None,
                "vehicle_description": None,
            },
        }

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_extractor)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-extract",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "I have a flat tire, I'm at 6th Street, my last name is Johnson.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = test_client.post("/vapi/tools", json=payload)

        assert response.status_code == 200
        parsed_result = json.loads(response.json()["results"][0]["result"])

        assert parsed_result["customer"]["last_name"] == "Johnson"
        assert parsed_result["service"]["location"] == "6th Street"
        assert parsed_result["service"]["complaint"] == "Flat tire"
        assert parsed_result["current_phase"] == "customer_intake"
        assert parsed_result["missing_fields"] == ["first_name", "phone"]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_does_not_overwrite_existing_values(monkeypatch) -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    call_id = "call-get-case-status-no-overwrite"
    session_store.set(
        call_id,
        {
            "last_name": "Smith",
            "services": [{"service_location": "Old Location"}],
        },
    )

    async def fake_extractor(message: str):  # noqa: ANN001
        assert isinstance(message, str)
        return {
            "customer": {
                "first_name": "Alice",
                "last_name": "Johnson",
                "phone": None,
                "company": None,
            },
            "service": {
                "location": "New Location",
                "complaint": "Dead battery",
                "unit_number": None,
                "vin": None,
                "vehicle_description": None,
            },
        }

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_extractor)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-no-overwrite",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "Actually my last name is Johnson and I'm at New Location.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = test_client.post("/vapi/tools", json=payload)

        assert response.status_code == 200
        parsed_result = json.loads(response.json()["results"][0]["result"])

        # Existing values should not be overwritten.
        assert parsed_result["customer"]["last_name"] == "Smith"
        assert parsed_result["service"]["location"] == "Old Location"

        # Missing values should be filled.
        assert parsed_result["customer"]["first_name"] == "Alice"
        assert parsed_result["service"]["complaint"] == "Dead battery"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_extractor_failure_does_not_break_tool(monkeypatch) -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    call_id = "call-get-case-status-extractor-failure"
    session_store.clear(call_id)

    async def fake_extractor(message: str):  # noqa: ANN001
        raise RuntimeError("LLM down")

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_extractor)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-extractor-failure",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": call_id,
                                    "last_user_message": "My last name is Johnson.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = test_client.post("/vapi/tools", json=payload)

        assert response.status_code == 200
        parsed_result = json.loads(response.json()["results"][0]["result"])

        # No extraction applied; legacy defaults remain.
        assert parsed_result["missing_fields"] == ["first_name", "last_name", "phone"]
        assert parsed_result["customer"]["last_name"] is None
    finally:
        app.dependency_overrides.pop(get_database_client, None)

