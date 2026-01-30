"""get_case_status: use assistant-request overrides to prefill known customer."""

import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class ExplodingDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        raise AssertionError("DB lookup should be skipped when overrides are present")


def _post_get_case_status(
    *,
    test_client: TestClient,
    call_id: str,
    call_overrides: dict,
    tool_args: dict | None = None,
) -> dict:
    tool_args = tool_args or {"call_id": call_id}
    token = "test-secret"
    previous_token = os.environ.get("TOOLS_TOKEN")
    os.environ["TOOLS_TOKEN"] = token
    payload = {
        "call": {"id": call_id, **call_overrides},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status-overrides",
                "name": "get_case_status",
                "arguments": tool_args,
            }
        ],
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


def test_get_case_status_prefers_assistant_overrides_for_known_customer() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-known-overrides"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "assistantOverrides": {
                "variableValues": {
                    "customerName": "John Johnson",
                    "customerId": "160e88ba-c429-4831-8099-3dd7eea72d90",
                    "customerPhone": "+15551230000",
                    "companyName": "Acme Logistics",
                    "isKnownCustomer": "true",
                }
            }
        }

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
        )

        # Assert
        assert parsed_result["customer"] == {
            "id": "160e88ba-c429-4831-8099-3dd7eea72d90",
            "first_name": "John",
            "last_name": "Johnson",
            "phone": "+15551230000",
            "email": None,
            "company": "Acme Logistics",
        }
        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"] == {
            "to_service_collection": True,
            "to_booking": False,
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_reads_squad_overrides_when_present() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-squad-overrides"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "squadOverrides": {
                "variableValues": {
                    "customerName": "Maria Gomez",
                    "customerId": "customer-123",
                    "customerPhone": "+15551239999",
                    "companyName": "",
                    "isKnownCustomer": "true",
                }
            }
        }

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
        )

        # Assert
        assert parsed_result["customer"]["id"] == "customer-123"
        assert parsed_result["customer"]["first_name"] == "Maria"
        assert parsed_result["customer"]["last_name"] == "Gomez"
        assert parsed_result["ready_for_handoff"]["to_service_collection"] is True
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_ignores_overrides_when_customer_unknown() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-unknown-overrides"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "assistantOverrides": {
                "variableValues": {
                    "customerName": "Ignored Name",
                    "customerId": "ignored-id",
                    "customerPhone": "+15551238888",
                    "companyName": "Ignored Co",
                    "isKnownCustomer": "false",
                }
            }
        }

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
        )

        # Assert
        assert parsed_result["customer"]["id"] == "ignored-id"
        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["missing_fields"] == [
            "vehicle_identifier",
            "location",
            "complaint",
        ]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_fast_path_prompts_for_vehicle_info() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-fast-path-vehicle"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "assistantOverrides": {
                "variableValues": {
                    "customerName": "Casey Lee",
                    "customerId": "cust-vehicle-1",
                    "customerPhone": "+15551235555",
                    "companyName": "Roadside Co",
                    "isKnownCustomer": "true",
                }
            }
        }

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
            tool_args={"call_id": call_id, "last_user_message": "Yes"},
        )

        # Assert
        assert parsed_result["customer"]["id"] == "cust-vehicle-1"
        assert parsed_result["customer"]["first_name"] == "Casey"
        assert parsed_result["customer"]["last_name"] == "Lee"
        assert parsed_result["customer"]["phone"] == "+15551235555"
        assert parsed_result["customer"]["company"] == "Roadside Co"
        assert parsed_result["missing_fields"] == [
            "vehicle_identifier",
            "location",
            "complaint",
        ]
        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["ready_for_handoff"] == {
            "to_service_collection": True,
            "to_booking": False,
        }
        assert parsed_result["next_action"] == "Ask for the vehicle's VIN, unit number, or nickname."
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "What vehicle do you need service for?"
        assert parsed_result["then_action"] == "collect_service_info"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_fast_path_prioritizes_location_when_vehicle_known() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-fast-path-location"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "vin_number": "1HGCM82633A123456",
                }
            ]
        },
    )

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "assistantOverrides": {
                "variableValues": {
                    "customerName": "Riley Park",
                    "customerId": "cust-location-1",
                    "customerPhone": "+15551234444",
                    "companyName": "",
                    "isKnownCustomer": "false",
                }
            }
        }

        # Act
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
        )

        # Assert
        assert parsed_result["missing_fields"] == ["location", "complaint"]
        assert parsed_result["next_action"] == "Ask where the vehicle is located."
        assert parsed_result["immediate_message"] == "Where is the vehicle located?"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_fast_path_skips_network_dependencies() -> None:
    """Regression guard: known-customer overrides must not require a DB or network."""
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-case-status-fast-path-no-network"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: ExplodingDatabaseClient()
    try:
        test_client = TestClient(app)
        overrides = {
            "assistantOverrides": {
                "variableValues": {
                    "customerName": "Jordan Miles",
                    "customerId": "cust-no-network",
                    "customerPhone": "+15551236666",
                    "companyName": "Fleet Ops",
                    "isKnownCustomer": "true",
                }
            }
        }

        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            call_overrides=overrides,
            tool_args={"call_id": call_id, "last_user_message": "Yes"},
        )

        assert parsed_result["customer"]["id"] == "cust-no-network"
        assert parsed_result["response_mode"] == "speak_first"
    finally:
        app.dependency_overrides.pop(get_database_client, None)
