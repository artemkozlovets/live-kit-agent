from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(
        self,
        customer_id_to_return: str | None,
        unit_id_to_return: str,
    ) -> None:
        self.customer_id_to_return = customer_id_to_return
        self.unit_id_to_return = unit_id_to_return

    def find_customer_for_unit_creation(self, store_unit_args):
        return self.customer_id_to_return

    def create_unit(self, store_unit_args, customer_id: str):
        return self.unit_id_to_return


def test_store_unit_returns_created_unit_id() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(
        customer_id_to_return="CUST-123",
        unit_id_to_return="UNIT-456",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "company_name": "Acme Trucking",
                    "phone_number": "555-123-4567",
                    "email_address": "john@acme.com",
                    "vin_number": "1HGCM82633A004352",
                    "unit_number": "Truck-5",
                    "unit_nickname": "Main truck",
                    "license_plate_number": "ABC123",
                    "license_plate_state": "TX",
                    "chassis_type": "truck",
                    "unit_subtype": "box",
                }
            }
        }

        # Act
        response = test_client.post("/storeUnit", json=request_payload)

        # Assert
        assert response.status_code == 201
        assert response.json() == {"customer_id": "CUST-123", "unit_id": "UNIT-456"}
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_store_unit_missing_customer_returns_not_found() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(
        customer_id_to_return=None,
        unit_id_to_return="UNIT-456",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "company_name": "Acme Trucking",
                    "phone_number": "555-123-4567",
                    "email_address": "john@acme.com",
                    "vin_number": "1HGCM82633A004352",
                    "unit_number": "Truck-5",
                    "unit_nickname": "Main truck",
                    "license_plate_number": "ABC123",
                    "license_plate_state": "TX",
                    "chassis_type": "truck",
                    "unit_subtype": "box",
                }
            }
        }

        # Act
        response = test_client.post("/storeUnit", json=request_payload)

        # Assert
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_database_client, None)

