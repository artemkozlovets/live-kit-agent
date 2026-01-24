"""TDD Step 3: validate_phone tool behavior (MVP).

MVP decisions:
- validate_phone does format + normalization only
- returns is_mobile=False (SMS not configured)
- increments phone_attempts on invalid input
"""

import json

from fastapi.testclient import TestClient


def test_validate_phone_valid_returns_formatted_e164_and_is_mobile_false() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-validate-phone-valid"},
            "toolCallList": [
                {
                    "id": "tool-call-validate-phone-valid",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "305-317-9840"}),
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
    first_result = response_data["results"][0]
    parsed_result = json.loads(first_result["result"])

    assert parsed_result == {
        "valid": True,
        "is_mobile": False,
        "formatted": "+13053179840",
        "next_action": "Immediately call check_customer with phone_number=+13053179840. Do not wait for user input.",
    }


def test_validate_phone_invalid_increments_attempt_counter_in_session() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-validate-phone-invalid"
    session_store.clear(call_id)

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-validate-phone-invalid-1",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "123"}),
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
    first_result = response_data["results"][0]
    parsed_result = json.loads(first_result["result"])

    assert parsed_result["valid"] is False
    assert parsed_result["attempt"] == 1
    assert parsed_result["max_attempts"] == 3

    stored_session = session_store.get(call_id)
    assert stored_session["phone_attempts"] == 1


def test_validate_phone_double_country_code_still_normalizes() -> None:
    """Edge case: model may prepend +1 to a number that already includes a leading 1."""
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-validate-phone-double-country-code"},
            "toolCallList": [
                {
                    "id": "tool-call-validate-phone-double-country-code",
                    "function": {
                        "name": "validate_phone",
                        # Reason: Caller may say "1 305..." and the model may still add +1.
                        "arguments": json.dumps({"phone_number": "+113053179840"}),
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
    first_result = response_data["results"][0]
    parsed_result = json.loads(first_result["result"])

    assert parsed_result == {
        "valid": True,
        "is_mobile": False,
        "formatted": "+13053179840",
        "next_action": "Immediately call check_customer with phone_number=+13053179840. Do not wait for user input.",
    }
