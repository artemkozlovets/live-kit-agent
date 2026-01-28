from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_variable_values_map_into_existing_override_path(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-variable-values"},
        "assistant": {
            "variable_values": {
                "customerId": "CUST-123",
                "isKnownCustomer": "true",
            }
        },
        "tool_calls": [
            {
                "id": "tool-call-get-case-status",
                "name": "get_case_status",
                "arguments": {
                    "last_user_message": "Hi",
                    "expected_field": None,
                },
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["ok"] is True
    result_obj = results[0]["result"]
    assert result_obj["current_phase"] == "service_collection"

