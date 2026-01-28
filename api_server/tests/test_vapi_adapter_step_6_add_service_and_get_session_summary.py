"""TDD Step 6: add_service + get_session_summary.

Behaviors:
- add_service requires at least one of vin_number, unit_number, unit_nickname
- cap services to 5 per call
- get_session_summary returns service_count and services list
"""

import os

from fastapi.testclient import TestClient


def _post_tool(*, test_client: TestClient, call_id: str, tool_call_id: str, name: str, arguments: dict) -> dict:
    token = "test-secret"
    previous_token = os.environ.get("TOOLS_TOKEN")
    os.environ["TOOLS_TOKEN"] = token
    payload = {
        "call": {"id": call_id},
        "tool_calls": [{"id": tool_call_id, "name": name, "arguments": arguments}],
    }
    try:
        response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": token})
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["results"][0]["ok"] is True
        return response_data["results"][0]["result"]
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token


def test_add_service_requires_vehicle_identifier() -> None:
    # Arrange
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-add-service-missing-vehicle-id"
    session_store.clear(call_id)

    test_client = TestClient(app)

    # Act
    parsed_result = _post_tool(
        test_client=test_client,
        call_id=call_id,
        tool_call_id="tool-call-add-service-missing-vehicle-id",
        name="add_service",
        arguments={
            "service_complaint": "Oil change",
            "service_location": "Denver CO",
        },
    )

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

    # Act
    parsed_result = _post_tool(
        test_client=test_client,
        call_id=call_id,
        tool_call_id="tool-call-add-service-6",
        name="add_service",
        arguments={
            "unit_number": "UNIT-6",
            "service_complaint": "Tire rotation",
            "service_location": "Denver CO",
        },
    )

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

    # Act
    parsed_result = _post_tool(
        test_client=test_client,
        call_id=call_id,
        tool_call_id="tool-call-get-session-summary",
        name="get_session_summary",
        arguments={},
    )

    assert parsed_result["service_count"] == 2
    assert len(parsed_result["services"]) == 2
