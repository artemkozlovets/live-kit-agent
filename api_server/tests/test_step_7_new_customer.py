from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, customer_id_to_return: str) -> None:
        self.customer_id_to_return = customer_id_to_return

    def create_customer(self, new_customer_args):
        return self.customer_id_to_return


def test_new_customer_returns_created_customer_id() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(customer_id_to_return="CUST-123")

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "company_name": "Acme Trucking",
                    "email_address": "john@acme.com",
                    "phone_number": "555-123-4567",
                    "customer_position": "fleet manager",
                    "marketing_source": "google",
                    "streetAddress": "123 Main St",
                    "city": "Dallas",
                    "state": "TX",
                    "country": "US",
                    "postalCode": "75201",
                }
            }
        }

        # Act
        response = test_client.post("/newCustomer", json=request_payload)

        # Assert
        assert response.status_code == 201
        assert response.json() == {"customer_id": "CUST-123"}
    finally:
        app.dependency_overrides.pop(get_database_client, None)

