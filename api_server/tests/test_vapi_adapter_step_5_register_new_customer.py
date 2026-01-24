"""TDD Step 5: register_new_customer uses backend-shaped fields and stores customer_id."""

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, customer_id_to_return: str) -> None:
        self.customer_id_to_return = customer_id_to_return
        self.captured_new_customer_args = None

    def create_customer(self, new_customer_args):
        self.captured_new_customer_args = new_customer_args
        return self.customer_id_to_return


def test_register_new_customer_stores_customer_id_in_session_and_normalizes_phone() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-register-new-customer"
    session_store.clear(call_id)

    fake_database_client = FakeDatabaseClient(customer_id_to_return="CUST-999")
    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-register-new-customer",
                        "function": {
                            "name": "register_new_customer",
                            "arguments": json.dumps(
                                {
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
            "customer_id": "CUST-999",
            "next_action": "Customer registered. Proceed to service collection. Call handoff_to_ServiceCollection.",
        }
        assert fake_database_client.captured_new_customer_args.phone_number == "+15551234567"

        stored_session = session_store.get(call_id)
        assert stored_session["customer_id"] == "CUST-999"
    finally:
        app.dependency_overrides.pop(get_database_client, None)

