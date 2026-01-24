"""TDD Step 11: get_case_status tool.

This tool gives any assistant a real-time view of what we currently know about the call
and what to ask for next.
"""

import json

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, *, customers_by_id: dict[str, CustomerRecord] | None = None) -> None:
        self.customers_by_id = customers_by_id or {}

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        return self.customers_by_id.get(customer_id)


def test_get_case_status_new_call_returns_customer_intake_defaults() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-new"
    session_store.clear(call_id)

    fake_database_client = FakeDatabaseClient()
    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)
        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-new",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps({"call_id": call_id}),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        # Act
        response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        parsed_result = json.loads(response_data["results"][0]["result"])

        assert parsed_result == {
            "customer": {
                "id": None,
                "first_name": None,
                "last_name": None,
                "phone": None,
                "email": None,
                "company": None,
            },
            "service": {
                "id": None,
                "vin": None,
                "unit_number": None,
                "unit_nickname": None,
                "location": None,
                "location_is_safe": None,
                "is_mobile": None,
                "complaint": None,
            },
            "booking": {
                "id": None,
                "eta": None,
                "technician": None,
                "status": None,
            },
            "missing_fields": ["first_name", "last_name", "phone"],
            "current_phase": "customer_intake",
            "ready_for_handoff": {
                "to_service_collection": False,
                "to_booking": False,
            },
            "next_action": "This is a new call. Start by collecting the customer's name.",
            "validation_state": {
                "phone_attempts": 0,
                "vin_attempts": 0,
                "vin_fallback_triggered": False,
            },
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_vin_fallback_triggered_prioritizes_unit_number() -> None:
    """Edge case: after 3 VIN validation failures, we should stop asking for VIN."""
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-vin-fallback"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "vin_attempts": 3,
            "services": [
                {
                    "service_location": "123 Main St, Denver CO",
                    "service_complaint": "Flat tire",
                }
            ],
        },
    )

    fake_database_client = FakeDatabaseClient(
        customers_by_id={
            "CUST-123": CustomerRecord(
                customer_id="CUST-123",
                customer_name="John Smith",
                phone_number="+15551234567",
            )
        }
    )
    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)
        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-vin-fallback",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps({"call_id": call_id}),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        # Act
        response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        parsed_result = json.loads(response_data["results"][0]["result"])

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["missing_fields"] == ["unit_number"]
        assert parsed_result["next_action"] == (
            "VIN validation failed 3 times. Ask for the unit number or a nickname for the vehicle instead."
        )
        assert parsed_result["validation_state"] == {
            "phone_attempts": 0,
            "vin_attempts": 3,
            "vin_fallback_triggered": True,
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_unknown_customer_id_gracefully_degrades_to_customer_intake() -> None:
    """Failure case: session has customer_id, but DB lookup fails."""
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-missing-customer"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-MISSING",
            "phone_attempts": 2,
            "vin_attempts": 1,
        },
    )

    fake_database_client = FakeDatabaseClient(customers_by_id={})
    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)
        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-missing-customer",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps({"call_id": call_id}),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        # Act
        response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        parsed_result = json.loads(response_data["results"][0]["result"])

        assert parsed_result["customer"]["id"] is None
        assert parsed_result["current_phase"] == "customer_intake"
        assert parsed_result["missing_fields"] == ["first_name", "last_name", "phone"]
        assert parsed_result["validation_state"] == {
            "phone_attempts": 2,
            "vin_attempts": 1,
            "vin_fallback_triggered": False,
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)

