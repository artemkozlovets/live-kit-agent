"""Tests for Vapi assistant-request webhook handling."""

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client

SQUAD_ID = "52cd942d-f789-405c-bd1c-50fdb2037c29"


class FakeDatabaseClient:
    def __init__(self, customer: CustomerRecord | None = None, should_raise: bool = False) -> None:
        self.customer = customer
        self.should_raise = should_raise

    def find_customer_by_phone_number(self, inbound_args):
        if self.should_raise:
            raise RuntimeError("DB is down")
        if self.customer and inbound_args.phone_number == self.customer.phone_number:
            return self.customer
        return None


def test_assistant_request_known_customer_returns_squad_overrides() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    customer = CustomerRecord(
        customer_id="customer-uuid",
        customer_name="John Doe",
        phone_number="+15551234567",
        company_name="ABC Trucking",
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(customer=customer)
    try:
        test_client = TestClient(app)

        payload = {
            "message": {
                "type": "assistant-request",
                "call": {"id": "call-1", "customer": {"number": "+15551234567"}},
                "phoneNumber": {"id": "phone-1", "number": "+19519008210"},
            }
        }

        # Act
        response = test_client.post("/vapi/assistant-request", json=payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {
            "squadId": SQUAD_ID,
            "squadOverrides": {
                "variableValues": {
                    "customerName": "John Doe",
                    "customerPhone": "+15551234567",
                    "customerId": "customer-uuid",
                    "companyName": "ABC Trucking",
                    "isKnownCustomer": "true",
                }
            },
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_assistant_request_missing_phone_returns_blank_variables() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)

        payload = {
            "message": {
                "type": "assistant-request",
                "call": {"id": "call-2", "customer": {}},
                "phoneNumber": {"id": "phone-1", "number": "+19519008210"},
            }
        }

        # Act
        response = test_client.post("/vapi/assistant-request", json=payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {
            "squadId": SQUAD_ID,
            "squadOverrides": {
                "variableValues": {
                    "customerName": "",
                    "customerPhone": "",
                    "customerId": "",
                    "companyName": "",
                    "isKnownCustomer": "false",
                }
            },
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_assistant_request_db_error_falls_back_to_unknown_customer() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient(should_raise=True)
    try:
        test_client = TestClient(app)

        payload = {
            "message": {
                "type": "assistant-request",
                "call": {"id": "call-3", "customer": {"number": "+15551230000"}},
                "phoneNumber": {"id": "phone-1", "number": "+19519008210"},
            }
        }

        # Act
        response = test_client.post("/vapi/assistant-request", json=payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {
            "squadId": SQUAD_ID,
            "squadOverrides": {
                "variableValues": {
                    "customerName": "",
                    "customerPhone": "+15551230000",
                    "customerId": "",
                    "companyName": "",
                    "isKnownCustomer": "false",
                }
            },
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)
