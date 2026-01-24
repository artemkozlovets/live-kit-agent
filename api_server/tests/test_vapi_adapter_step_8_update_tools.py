"""TDD Step 8: update_customer + update_service_order handlers."""

import json

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord, ServiceOrderRecord, UnitRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(
        self,
        *,
        customers_by_id: dict[str, CustomerRecord] | None = None,
        customers_by_phone: dict[str, CustomerRecord] | None = None,
        service_orders_by_id: dict[str, ServiceOrderRecord] | None = None,
        units_by_vin_number: dict[str, UnitRecord] | None = None,
        units_by_unit_number: dict[str, UnitRecord] | None = None,
        units_by_nickname: dict[str, list[UnitRecord]] | None = None,
    ) -> None:
        self.customers_by_id = customers_by_id or {}
        self.customers_by_phone = customers_by_phone or {}
        self.service_orders_by_id = service_orders_by_id or {}
        self.units_by_vin_number = units_by_vin_number or {}
        self.units_by_unit_number = units_by_unit_number or {}
        self.units_by_nickname = units_by_nickname or {}
        self.updated_customers: list[tuple[str, dict[str, object]]] = []
        self.updated_service_orders: list[tuple[str, dict[str, object]]] = []

    def find_customer_by_id(self, customer_id: str):
        return self.customers_by_id.get(customer_id)

    def find_customer_by_phone_number(self, inbound_args):
        return self.customers_by_phone.get(inbound_args.phone_number)

    def update_customer(self, customer_id: str, updates: dict[str, object]):
        self.updated_customers.append((customer_id, updates))
        return customer_id

    def find_service_order_by_id(self, order_id: str):
        return self.service_orders_by_id.get(order_id)

    def update_service_order(self, order_id: str, updates: dict[str, object]):
        self.updated_service_orders.append((order_id, updates))
        return order_id

    def find_unit_by_vin_number(self, check_vin_args):
        return self.units_by_vin_number.get(check_vin_args.vin_number)

    def find_unit_by_unit_number(self, customer_id: str, unit_number: str):
        _ = customer_id
        return self.units_by_unit_number.get(unit_number)

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str):
        _ = customer_id
        return self.units_by_nickname.get(unit_nickname, [])

    def create_unit(self, store_unit_args, customer_id: str):
        _ = store_unit_args
        return f"UNIT-AUTO-{customer_id}"


def test_update_customer_updates_fields_and_session_phone() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-update-customer-success"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-1",
            "phone_number": "+15550001111",
        },
    )

    fake_database_client = FakeDatabaseClient(
        customers_by_id={
            "CUST-1": CustomerRecord(
                customer_id="CUST-1",
                customer_name="Bob Smith",
                phone_number="+15550001111",
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
                        "id": "tool-call-update-customer-success",
                        "function": {
                            "name": "update_customer",
                            "arguments": json.dumps(
                                {
                                    "customer_id": "CUST-1",
                                    "updates": {
                                        "first_name": "Robert",
                                        "phone_number": "+15550002222",
                                        "email_address": "rob@example.com",
                                    },
                                }
                            ),
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
            "success": True,
            "updated_fields": ["first_name", "phone_number", "email_address"],
            "customer_id": "CUST-1",
            "next_action": "Customer information updated. Continue with the call.",
        }
        assert fake_database_client.updated_customers == [
            (
                "CUST-1",
                {
                    "first_name": "Robert",
                    "phone_number": "+15550002222",
                    "email_address": "rob@example.com",
                    "contact_name": "Robert Smith",
                },
            )
        ]
        assert session_store.get(call_id)["phone_number"] == "+15550002222"
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_customer_uses_phone_lookup_when_id_missing() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-update-customer-phone"
    session_store.clear(call_id)

    fake_database_client = FakeDatabaseClient(
        customers_by_phone={
            "+15550003333": CustomerRecord(
                customer_id="CUST-2",
                customer_name="Alice Johnson",
                phone_number="+15550003333",
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
                        "id": "tool-call-update-customer-phone",
                        "function": {
                            "name": "update_customer",
                            "arguments": json.dumps(
                                {
                                    "phone_number": "+15550003333",
                                    "updates": {"last_name": "Smith"},
                                }
                            ),
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
            "success": True,
            "updated_fields": ["last_name"],
            "customer_id": "CUST-2",
            "next_action": "Customer information updated. Continue with the call.",
        }
        assert fake_database_client.updated_customers == [
            (
                "CUST-2",
                {
                    "last_name": "Smith",
                    "contact_name": "Alice Smith",
                },
            )
        ]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_customer_missing_identifier_returns_error() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-update-customer-missing-id"
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
                        "id": "tool-call-update-customer-missing-id",
                        "function": {
                            "name": "update_customer",
                            "arguments": json.dumps(
                                {
                                    "updates": {"email_address": "new@example.com"},
                                }
                            ),
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
            "success": False,
            "error": "No customer identifier provided",
            "next_action": "Ask caller to confirm their phone number.",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_service_order_updates_session_service() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-update-service-session"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "unit_number": "UNIT-1",
                    "service_location": "123 Old Street",
                    "service_complaint": "Flat tire",
                },
                {
                    "unit_number": "UNIT-2",
                    "service_location": "456 Old Avenue",
                    "service_complaint": "Old complaint",
                },
            ]
        },
    )

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
                        "id": "tool-call-update-service-session",
                        "function": {
                            "name": "update_service_order",
                            "arguments": json.dumps(
                                {
                                    "updates": {
                                        "service_location": "456 Pine Avenue, Dallas",
                                        "unit_nickname": "Big Green",
                                    }
                                }
                            ),
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
            "success": True,
            "updated_fields": ["service_location", "unit_nickname"],
            "order_id": "session",
            "next_action": "Service order updated. Continue with the call.",
        }

        updated_session = session_store.get(call_id)
        assert updated_session["services"][-1] == {
            "unit_number": "UNIT-2",
            "service_location": "456 Pine Avenue, Dallas",
            "service_complaint": "Old complaint",
            "unit_nickname": "Big Green",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_service_order_updates_stored_order_with_unit_resolution() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(
        service_orders_by_id={
            "ORD-1": ServiceOrderRecord(
                service_order_id="ORD-1",
                customer_id="CUST-9",
                unit_id="UNIT-OLD",
            )
        },
        units_by_nickname={
            "Big Green": [
                UnitRecord(
                    unit_id="UNIT-NEW",
                    vin_number="VIN-NEW",
                    unit_number="UNIT-99",
                    unit_nickname="Big Green",
                )
            ]
        },
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": "call-update-service-db"},
                "toolCallList": [
                    {
                        "id": "tool-call-update-service-db",
                        "function": {
                            "name": "update_service_order",
                            "arguments": json.dumps(
                                {
                                    "order_id": "ORD-1",
                                    "updates": {
                                        "unit_nickname": "Big Green",
                                        "service_complaint": "Dead battery",
                                    },
                                }
                            ),
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
            "success": True,
            "updated_fields": ["unit_nickname", "service_complaint"],
            "order_id": "ORD-1",
            "next_action": "Service order updated. Continue with the call.",
        }
        assert fake_database_client.updated_service_orders == [
            (
                "ORD-1",
                {
                    "unit_nickname": "Big Green",
                    "service_complaint": "Dead battery",
                    "unit_id": "UNIT-NEW",
                },
            )
        ]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_service_order_missing_session_services_returns_error() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-update-service-missing"
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
                        "id": "tool-call-update-service-missing",
                        "function": {
                            "name": "update_service_order",
                            "arguments": json.dumps(
                                {
                                    "updates": {"service_location": "456 Pine Avenue, Dallas"},
                                }
                            ),
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
            "success": False,
            "error": "No services in session",
            "next_action": "No service has been added yet. Collect service details first.",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)
