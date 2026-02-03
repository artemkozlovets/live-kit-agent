"""TDD Step 7: store_service_order fail-fast + session lifecycle."""

import os

from fastapi.testclient import TestClient

from api_server.models.database_records import UnitForServiceOrderRecord, UnitRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(
        self,
        *,
        customer_exists: bool,
        unit_records_for_service_order: dict[str, UnitForServiceOrderRecord | None],
        units_by_vin_number: dict[str, UnitRecord],
        units_by_unit_number: dict[str, UnitRecord],
        units_by_nickname: dict[str, list[UnitRecord]],
        service_order_ids_to_return: list[str],
    ) -> None:
        self.customer_exists_value = customer_exists
        self.unit_records_for_service_order = unit_records_for_service_order
        self.units_by_vin_number = units_by_vin_number
        self.units_by_unit_number = units_by_unit_number
        self.units_by_nickname = units_by_nickname
        self.service_order_ids_to_return = list(service_order_ids_to_return)
        self.created_service_orders = []
        self.created_units = []

    def customer_exists(self, store_service_order_args) -> bool:
        return self.customer_exists_value

    def find_unit_for_service_order(self, store_service_order_args):
        unit_id = store_service_order_args.unit_id
        return self.unit_records_for_service_order.get(unit_id)

    def find_unit_by_vin_number(self, check_vin_args):
        return self.units_by_vin_number.get(check_vin_args.vin_number)

    def find_unit_by_unit_number(self, customer_id: str, unit_number: str):
        _ = customer_id
        return self.units_by_unit_number.get(unit_number)

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str):
        _ = customer_id
        return self.units_by_nickname.get(unit_nickname, [])

    def create_unit(self, store_unit_args, customer_id: str):
        unit_id = f"UNIT-AUTO-{len(self.created_units) + 1}"
        self.created_units.append(store_unit_args)
        self.unit_records_for_service_order[unit_id] = UnitForServiceOrderRecord(
            unit_id=unit_id,
            customer_id=customer_id,
        )
        return unit_id

    def create_service_order(self, store_service_order_args):
        self.created_service_orders.append(store_service_order_args)
        return self.service_order_ids_to_return.pop(0)


def test_store_service_order_missing_unit_auto_creates_and_marks_session_completed() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-store-service-order-fail-fast"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "services": [
                {
                    "unit_number": "UNIT-1",
                    "service_complaint": "Oil change",
                    "service_location": "Denver CO",
                },
                {
                    "unit_number": "UNIT-404",
                    "service_complaint": "Tire rotation",
                    "service_location": "Denver CO",
                },
            ],
        },
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_records_for_service_order={
            "UNIT-1": UnitForServiceOrderRecord(unit_id="UNIT-1", customer_id="CUST-123"),
        },
        units_by_vin_number={},
        units_by_unit_number={
            "UNIT-1": UnitRecord(unit_id="UNIT-1", vin_number="VIN-1", unit_number="UNIT-1"),
        },
        units_by_nickname={},
        service_order_ids_to_return=["SO-1", "SO-2"],
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    previous_token = os.environ.get("TOOLS_TOKEN")
    try:
        test_client = TestClient(app)
        token = "test-secret"
        os.environ["TOOLS_TOKEN"] = token

        vapi_tool_call_payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {"id": "tool-call-confirm-services", "name": "confirm_services", "arguments": {}},
                {"id": "tool-call-store-service-order-fail-fast", "name": "store_service_order", "arguments": {}},
            ],
        }

        # Act
        response = test_client.post("/tools", json=vapi_tool_call_payload, headers={"X-TOOLS-TOKEN": token})

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        results = response_data["results"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is True
        parsed_result = results[1]["result"]

        assert parsed_result == {
            "success": True,
            "order_ids": ["SO-1", "SO-2"],
            "next_action": "Order confirmed. Call send_confirmation_sms, then thank the caller and end the call.",
        }
        assert len(fake_database_client.created_units) == 1
        assert len(fake_database_client.created_service_orders) == 2

        stored_session = session_store.get(call_id)
        assert stored_session.get("current_phase") == "completed"
        assert stored_session.get("customer_id") == "CUST-123"
        assert stored_session.get("order_ids") == ["SO-1", "SO-2"]
        assert isinstance(stored_session.get("services"), list)
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token
        app.dependency_overrides.pop(get_database_client, None)


def test_store_service_order_auto_create_unit_uses_vehicle_make_model_from_service() -> None:
    """When auto-creating a unit, pass through make/model captured during the call."""

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-store-service-order-auto-create-make-model"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "services": [
                {
                    "unit_nickname": "Big Pete",
                    "vehicle_make": "Ford",
                    "vehicle_model": "F-150",
                    "service_complaint": "Flat tire",
                    "service_location": "Denver CO",
                },
            ],
        },
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_records_for_service_order={},
        units_by_vin_number={},
        units_by_unit_number={},
        units_by_nickname={},
        service_order_ids_to_return=["SO-1"],
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    previous_token = os.environ.get("TOOLS_TOKEN")
    try:
        test_client = TestClient(app)
        token = "test-secret"
        os.environ["TOOLS_TOKEN"] = token

        vapi_tool_call_payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {"id": "tool-call-confirm-services", "name": "confirm_services", "arguments": {}},
                {"id": "tool-call-store-service-order-make-model", "name": "store_service_order", "arguments": {}},
            ],
        }

        response = test_client.post("/tools", json=vapi_tool_call_payload, headers={"X-TOOLS-TOKEN": token})

        assert response.status_code == 200
        response_data = response.json()
        results = response_data["results"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is True

        assert len(fake_database_client.created_units) == 1
        created_unit_args = fake_database_client.created_units[0]
        assert created_unit_args.make == "Ford"
        assert created_unit_args.model == "F-150"
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token
        app.dependency_overrides.pop(get_database_client, None)


def test_store_service_order_success_creates_one_order_per_service_and_marks_session_completed() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-store-service-order-success"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "services": [
                {
                    "unit_number": "UNIT-1",
                    "service_complaint": "Oil change",
                    "service_location": "Denver CO",
                },
                {
                    "vin_number": "1HGCM82633A004352",
                    "service_complaint": "Brake inspection",
                    "service_location": "Boulder CO",
                },
            ],
        },
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_records_for_service_order={
            "UNIT-1": UnitForServiceOrderRecord(unit_id="UNIT-1", customer_id="CUST-123"),
            "UNIT-2-ID": UnitForServiceOrderRecord(unit_id="UNIT-2-ID", customer_id="CUST-123"),
        },
        units_by_vin_number={
            "1HGCM82633A004352": UnitRecord(
                unit_id="UNIT-2-ID", vin_number="1HGCM82633A004352", unit_number="UNIT-2"
            ),
        },
        units_by_unit_number={
            "UNIT-1": UnitRecord(unit_id="UNIT-1", vin_number="VIN-1", unit_number="UNIT-1"),
        },
        units_by_nickname={},
        service_order_ids_to_return=["SO-1", "SO-2"],
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    previous_token = os.environ.get("TOOLS_TOKEN")
    try:
        test_client = TestClient(app)
        token = "test-secret"
        os.environ["TOOLS_TOKEN"] = token

        vapi_tool_call_payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {"id": "tool-call-confirm-services", "name": "confirm_services", "arguments": {}},
                {"id": "tool-call-store-service-order-success", "name": "store_service_order", "arguments": {}},
            ],
        }

        # Act
        response = test_client.post("/tools", json=vapi_tool_call_payload, headers={"X-TOOLS-TOKEN": token})

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        results = response_data["results"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is True
        parsed_result = results[1]["result"]

        assert parsed_result == {
            "success": True,
            "order_ids": ["SO-1", "SO-2"],
            "next_action": "Order confirmed. Call send_confirmation_sms, then thank the caller and end the call.",
        }
        assert len(fake_database_client.created_service_orders) == 2
        stored_session = session_store.get(call_id)
        assert stored_session.get("current_phase") == "completed"
        assert stored_session.get("customer_id") == "CUST-123"
        assert stored_session.get("order_ids") == ["SO-1", "SO-2"]
        assert isinstance(stored_session.get("services"), list)
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token
        app.dependency_overrides.pop(get_database_client, None)
