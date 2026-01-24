"""TDD Step 6: add_service + get_session_summary.

Behaviors:
- add_service requires at least one of vin_number, unit_number, unit_nickname
- cap services to 5 per call
- get_session_summary returns service_count and services list
"""

import json

from fastapi.testclient import TestClient


def test_add_service_requires_vehicle_identifier() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-add-service-missing-vehicle-id"
    session_store.clear(call_id)

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-add-service-missing-vehicle-id",
                    "function": {
                        "name": "add_service",
                        "arguments": json.dumps(
                            {
                                "service_complaint": "Oil change",
                                "service_location": "Denver CO",
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

    assert parsed_result["added"] is False
    assert "error" in parsed_result


def test_add_service_caps_at_five_services() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-add-service-max-limit"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "unit_number": f"UNIT-{service_index}",
                    "service_complaint": f"Service {service_index}",
                    "service_location": "Denver CO",
                }
                for service_index in range(5)
            ]
        },
    )

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-add-service-6",
                    "function": {
                        "name": "add_service",
                        "arguments": json.dumps(
                            {
                                "unit_number": "UNIT-6",
                                "service_complaint": "Tire rotation",
                                "service_location": "Denver CO",
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
        "added": False,
        "error": "Maximum 5 services per call",
        "next_action": "Limit reached. Ask if caller wants to finalize current services or call back for more.",
    }


def test_get_session_summary_returns_services() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-get-session-summary"
    session_store.set(
        call_id,
        {
            "services": [
                {
                    "vin_number": "1HGCM82633A111111",
                    "service_complaint": "Brake inspection",
                    "service_location": "Boulder CO",
                },
                {
                    "unit_number": "UNIT-2",
                    "service_complaint": "Oil change",
                    "service_location": "Denver CO",
                },
            ]
        },
    )

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-get-session-summary",
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
    response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

    # Assert
    assert response.status_code == 200
    response_data = response.json()
    parsed_result = json.loads(response_data["results"][0]["result"])

    assert parsed_result["service_count"] == 2
    assert len(parsed_result["services"]) == 2

