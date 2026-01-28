"""TDD Step 11: get_case_status tool.

This tool gives any assistant a real-time view of what we currently know about the call
and what to ask for next.
"""

import os

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, *, customers_by_id: dict[str, CustomerRecord] | None = None) -> None:
        self.customers_by_id = customers_by_id or {}

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        return self.customers_by_id.get(customer_id)


def _post_get_case_status(*, test_client: TestClient, call_id: str, tool_call_id: str) -> dict:
    token = "test-secret"
    previous_token = os.environ.get("TOOLS_TOKEN")
    os.environ["TOOLS_TOKEN"] = token
    payload = {
        "call": {"id": call_id},
        "tool_calls": [{"id": tool_call_id, "name": "get_case_status", "arguments": {"call_id": call_id}}],
    }
    try:
        response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": token})
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["results"][0]["ok"] is True
        return response_data["results"][0]["result"]
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token


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

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            tool_call_id="tool-call-get-case-status-new",
        )

        assert parsed_result["customer"] == {
            "id": None,
            "first_name": None,
            "last_name": None,
            "phone": None,
            "email": None,
            "company": None,
        }
        assert parsed_result["service"] == {
            "id": None,
            "vin": None,
            "unit_number": None,
            "unit_nickname": None,
            "location": None,
            "location_is_safe": None,
            "is_mobile": None,
            "complaint": None,
        }
        assert parsed_result["booking"] == {
            "id": None,
            "eta": None,
            "technician": None,
            "status": None,
        }
        assert parsed_result["missing_fields"] == ["first_name", "last_name", "phone"]
        assert parsed_result["current_phase"] == "customer_intake"
        assert parsed_result["ready_for_handoff"] == {
            "to_service_collection": False,
            "to_booking": False,
        }
        assert parsed_result["next_action"] == "This is a new call. Start by collecting the customer's name."
        assert parsed_result["validation_state"] == {
            "phone_attempts": 0,
            "vin_attempts": 0,
            "vin_fallback_triggered": False,
        }
        assert "customer_known_data" in parsed_result
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

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            tool_call_id="tool-call-get-case-status-vin-fallback",
        )

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

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            tool_call_id="tool-call-get-case-status-missing-customer",
        )

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
