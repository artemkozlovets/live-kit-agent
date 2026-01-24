from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, customers_by_phone_number: dict[str, CustomerRecord]) -> None:
        self.customers_by_phone_number = customers_by_phone_number

    def find_customer_by_phone_number(self, inbound_args) -> CustomerRecord | None:
        return self.customers_by_phone_number.get(inbound_args.phone_number)


def test_inbound_existing_customer_returns_customer_details() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    customer_record = CustomerRecord(
        customer_id="CUST-123",
        customer_name="John Doe",
        phone_number="+15551234567",
    )

    fake_database_client = FakeDatabaseClient(
        customers_by_phone_number={
            "+15551234567": customer_record,
        }
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "phone_number": "+15551234567",
                }
            }
        }

        # Act
        response = test_client.post("/inbound", json=request_payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {
            "customer_exists": True,
            "customer_name": "John Doe",
            "customer_id": "CUST-123",
            "phone_number": "+15551234567",
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_inbound_missing_customer_returns_customer_exists_false() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(customers_by_phone_number={})

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "phone_number": "+19999999999",
                }
            }
        }

        # Act
        response = test_client.post("/inbound", json=request_payload)

        # Assert
        assert response.status_code == 404
        assert response.json() == {"customer_exists": False}
    finally:
        app.dependency_overrides.pop(get_database_client, None)
