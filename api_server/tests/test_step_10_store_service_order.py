from fastapi.testclient import TestClient

from api_server.models.database_records import UnitForServiceOrderRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(
        self,
        customer_exists: bool,
        unit_record_to_return: UnitForServiceOrderRecord | None,
        service_order_id_to_return: str,
    ) -> None:
        self.customer_exists_value = customer_exists
        self.unit_record_to_return = unit_record_to_return
        self.service_order_id_to_return = service_order_id_to_return

    def customer_exists(self, store_service_order_args) -> bool:
        return self.customer_exists_value

    def find_unit_for_service_order(self, store_service_order_args):
        return self.unit_record_to_return

    def create_service_order(self, store_service_order_args):
        return self.service_order_id_to_return


def test_store_service_order_returns_created_service_order_id() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    unit_record = UnitForServiceOrderRecord(
        unit_id="UNIT-456",
        customer_id="CUST-123",
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_record_to_return=unit_record,
        service_order_id_to_return="SO-789",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "customer_id": "CUST-123",
                    "unit_id": "UNIT-456",
                    "service_location": "Denver warehouse",
                    "service_complaint": "oil change",
                }
            }
        }

        # Act
        response = test_client.post("/storeServiceOrder", json=request_payload)

        # Assert
        assert response.status_code == 201
        assert response.json() == {"service_order_id": "SO-789"}
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_store_service_order_missing_customer_returns_not_found() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    unit_record = UnitForServiceOrderRecord(
        unit_id="UNIT-456",
        customer_id="CUST-123",
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=False,
        unit_record_to_return=unit_record,
        service_order_id_to_return="SO-789",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "customer_id": "CUST-123",
                    "unit_id": "UNIT-456",
                    "service_location": "Denver warehouse",
                    "service_complaint": "oil change",
                }
            }
        }

        # Act
        response = test_client.post("/storeServiceOrder", json=request_payload)

        # Assert
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_store_service_order_missing_unit_returns_not_found() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_record_to_return=None,
        service_order_id_to_return="SO-789",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "customer_id": "CUST-123",
                    "unit_id": "UNIT-456",
                    "service_location": "Denver warehouse",
                    "service_complaint": "oil change",
                }
            }
        }

        # Act
        response = test_client.post("/storeServiceOrder", json=request_payload)

        # Assert
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_store_service_order_unit_customer_mismatch_returns_bad_request() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    unit_record = UnitForServiceOrderRecord(
        unit_id="UNIT-456",
        customer_id="CUST-999",
    )

    fake_database_client = FakeDatabaseClient(
        customer_exists=True,
        unit_record_to_return=unit_record,
        service_order_id_to_return="SO-789",
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "customer_id": "CUST-123",
                    "unit_id": "UNIT-456",
                    "service_location": "Denver warehouse",
                    "service_complaint": "oil change",
                }
            }
        }

        # Act
        response = test_client.post("/storeServiceOrder", json=request_payload)

        # Assert
        assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(get_database_client, None)

