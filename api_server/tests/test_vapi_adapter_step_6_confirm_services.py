"""TDD Step 6: confirm_services.

Behaviors:
- confirm_services marks services_confirmed in session
- get_session_summary surfaces services_confirmed flag
"""

import json

from fastapi.testclient import TestClient


def test_confirm_services_marks_session_and_summary() -> None:
    """Expected use: confirm_services sets services_confirmed in summary."""
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-confirm-services"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "services": [
                {
                    "unit_number": "UNIT-1",
                    "service_complaint": "Flat tire",
                    "service_location": "Austin TX",
                }
            ]
        },
    )

    test_client = TestClient(app)

    confirm_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-confirm-services",
                    "function": {
                        "name": "confirm_services",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    summary_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-session-summary",
                    "function": {
                        "name": "get_session_summary",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    confirm_response = test_client.post("/vapi/tools", json=confirm_payload)
    summary_response = test_client.post("/vapi/tools", json=summary_payload)

    # Assert
    assert confirm_response.status_code == 200
    confirm_result = json.loads(confirm_response.json()["results"][0]["result"])
    assert confirm_result == {
        "confirmed": True,
        "next_action": "Services confirmed. Handoff to Booking.",
    }

    assert summary_response.status_code == 200
    summary_result = json.loads(summary_response.json()["results"][0]["result"])
    assert summary_result["service_count"] == 1
    assert summary_result["services_confirmed"] is True


def test_confirm_services_with_no_services_still_confirms() -> None:
    """Edge case: confirm_services should work even with no services yet."""
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-confirm-services-empty"
    session_store.set(call_id, {"customer_id": "CUST-EMPTY"})

    test_client = TestClient(app)

    confirm_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-confirm-services-empty",
                    "function": {
                        "name": "confirm_services",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    summary_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-session-summary-empty",
                    "function": {
                        "name": "get_session_summary",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    confirm_response = test_client.post("/vapi/tools", json=confirm_payload)
    summary_response = test_client.post("/vapi/tools", json=summary_payload)

    # Assert
    assert confirm_response.status_code == 200
    confirm_result = json.loads(confirm_response.json()["results"][0]["result"])
    assert confirm_result == {
        "confirmed": True,
        "next_action": "Services confirmed. Handoff to Booking.",
    }

    summary_result = json.loads(summary_response.json()["results"][0]["result"])
    assert summary_result["service_count"] == 0
    assert summary_result["services_confirmed"] is True


def test_confirm_services_missing_call_id_returns_error() -> None:
    """Failure case: missing call id should return an error."""
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    confirm_payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "tool-call-confirm-services-missing-call",
                    "function": {
                        "name": "confirm_services",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    confirm_response = test_client.post("/vapi/tools", json=confirm_payload)

    # Assert
    assert confirm_response.status_code == 200
    confirm_result = json.loads(confirm_response.json()["results"][0]["result"])
    assert confirm_result == {"confirmed": False, "error": "Missing call id"}


def test_confirm_services_missing_customer_returns_error() -> None:
    """Failure case: missing customer_id should return an error."""
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-confirm-services-missing-customer"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "unit_number": "UNIT-9",
                    "service_complaint": "Battery issue",
                    "service_location": "Dallas TX",
                }
            ]
        },
    )

    test_client = TestClient(app)

    confirm_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-confirm-services-missing-customer",
                    "function": {
                        "name": "confirm_services",
                        "arguments": json.dumps({}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    confirm_response = test_client.post("/vapi/tools", json=confirm_payload)

    # Assert
    assert confirm_response.status_code == 200
    confirm_result = json.loads(confirm_response.json()["results"][0]["result"])
    assert confirm_result == {
        "confirmed": False,
        "error": "Customer data required",
        "next_action": "Customer not identified. Call handoff_to_CustomerIntake to collect customer details.",
    }
