"""TDD Step 4: check_customer tool stores customer_id in session."""

import json

from fastapi.testclient import TestClient

from api_server.models.database_records import CustomerRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, customers_by_phone_number: dict[str, CustomerRecord]) -> None:
        self.customers_by_phone_number = customers_by_phone_number

    def find_customer_by_phone_number(self, inbound_args):
        return self.customers_by_phone_number.get(inbound_args.phone_number)


def test_check_customer_found_stores_customer_id_in_session_store() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-check-customer-found"
    session_store.clear(call_id)

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

        vapi_tool_call_payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-check-customer-found",
                        "function": {
                            "name": "check_customer",
                            "arguments": json.dumps({"phone_number": "+15551234567"}),
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
            "found": True,
            "customer": {
                "customer_id": "CUST-123",
                "customer_name": "John Doe",
                "phone_number": "+15551234567",
            },
            "next_action": "Greet John Doe by name and proceed to service collection. Call handoff_to_ServiceCollection.",
        }

        stored_session = session_store.get(call_id)
        assert stored_session["customer_id"] == "CUST-123"
    finally:
        app.dependency_overrides.pop(get_database_client, None)

