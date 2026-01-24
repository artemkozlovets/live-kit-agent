"""TDD Step 9: Handoff tool responses include destination and raw result string."""

import json

from fastapi.testclient import TestClient


HANDOFF_SERVICE_COLLECTION = "7eb8818b-16ff-4236-b4d1-9eca3c7d9972"
HANDOFF_CUSTOMER_INTAKE = "553a6ddd-6505-400b-9169-c6a0cf894dec"
HANDOFF_BOOKING = "53748b6f-2afe-4147-9ff7-e189acec4223"


def test_vapi_tools_handoff_returns_destination_and_results_for_all_tools() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-call-handoff-1"},
            "toolCallList": [
                {
                    "id": "tool-call-1",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "3053179840"}),
                    },
                },
                {
                    "id": "tool-call-2",
                    "function": {"name": "handoff_to_ServiceCollection", "arguments": "{}"},
                },
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

    # Assert
    assert response.status_code == 200

    response_data = response.json()
    assert "results" in response_data
    assert len(response_data["results"]) == 2

    first_result = response_data["results"][0]
    assert first_result["toolCallId"] == "tool-call-1"
    json.loads(first_result["result"])

    second_result = response_data["results"][1]
    assert second_result["toolCallId"] == "tool-call-2"
    assert second_result["result"] == "Transferring"

    assert response_data["destination"] == {
        "type": "assistant",
        "assistantId": HANDOFF_SERVICE_COLLECTION,
    }


def test_vapi_tools_handoff_uses_last_handoff_destination() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-call-handoff-2"},
            "toolCallList": [
                {
                    "id": "tool-call-1",
                    "function": {
                        "name": "handoff_to_CustomerIntake",
                        "arguments": "{}",
                    },
                },
                {
                    "id": "tool-call-2",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "3053179840"}),
                    },
                },
                {
                    "id": "tool-call-3",
                    "function": {"name": "handoff_to_Booking", "arguments": "{}"},
                },
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

    # Assert
    assert response.status_code == 200

    response_data = response.json()
    assert len(response_data["results"]) == 3
    assert response_data["results"][0]["result"] == "Transferring"
    json.loads(response_data["results"][1]["result"])
    assert response_data["results"][2]["result"] == "Transferring"

    assert response_data["destination"] == {
        "type": "assistant",
        "assistantId": HANDOFF_BOOKING,
    }


def test_vapi_tools_unknown_handoff_tool_has_no_destination() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-call-handoff-3"},
            "toolCallList": [
                {
                    "id": "tool-call-unknown",
                    "function": {
                        "name": "handoff_to_Unknown",
                        "arguments": "{}",
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
    assert "destination" not in response_data

    first_result = response_data["results"][0]
    parsed_result = json.loads(first_result["result"])
    assert "error" in parsed_result
    assert "handoff_to_Unknown" in parsed_result["error"]
