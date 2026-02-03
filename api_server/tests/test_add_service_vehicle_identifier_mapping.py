"""add_service mapping for OpenAI Realtime-friendly arguments."""

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


def test_add_service_accepts_vehicle_identifier_pair() -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-add-service-vehicle-identifier-pair"
    session_store.clear(call_id)

    test_client = TestClient(app)

    parsed_result = _post_tool(
        test_client=test_client,
        call_id=call_id,
        tool_call_id="tool-call-add-service-vehicle-identifier-pair",
        name="add_service",
        arguments={
            "vehicle_identifier_type": "unit_nickname",
            "vehicle_identifier": "Big Pete",
            "service_complaint": "Flat tire",
            "service_location": "Denver CO",
        },
    )

    assert parsed_result["added"] is True

    summary = _post_tool(
        test_client=test_client,
        call_id=call_id,
        tool_call_id="tool-call-get-session-summary-after-add",
        name="get_session_summary",
        arguments={},
    )

    assert summary["service_count"] == 1
    service = summary["services"][0]
    assert service["unit_nickname"] == "Big Pete"
    assert service["vehicle_id_type"] == "unit_nickname"
    assert "vehicle_identifier" not in service
    assert "vehicle_identifier_type" not in service
