from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, customer_id_to_return: str | None) -> None:
        self.customer_id_to_return = customer_id_to_return

    def update_customer_phone_number(self, update_number_request):
        return self.customer_id_to_return


def test_update_number_returns_customer_id() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(customer_id_to_return="CUST-123")

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "new_phone_number": "555-222-3333",
            "body": {
                "args": {
                    "first_name": "John",
                    "last_name": "Doe",
                }
            },
        }

        # Act
        response = test_client.post("/updateNumber", json=request_payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {"customer_id": "CUST-123"}
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_update_number_missing_customer_returns_not_found() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(customer_id_to_return=None)

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "new_phone_number": "555-222-3333",
            "body": {
                "args": {
                    "first_name": "John",
                    "last_name": "Doe",
                }
            },
        }

        # Act
        response = test_client.post("/updateNumber", json=request_payload)

        # Assert
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_database_client, None)

