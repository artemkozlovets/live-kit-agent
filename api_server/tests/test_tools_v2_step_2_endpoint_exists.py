from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_valid_token_dispatches_validate_phone(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-endpoint-exists"},
        "customer": {"number": "+15551234567"},
        "assistant": {"variable_values": {}},
        "tool_calls": [
            {
                "id": "tool-call-validate-phone",
                "name": "validate_phone",
                "arguments": {"phone_number": "305-317-9840"},
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    results = data.get("results")
    assert isinstance(results, list)
    assert len(results) == 1
    result0 = results[0]
    assert result0["tool_call_id"] == "tool-call-validate-phone"
    assert result0["name"] == "validate_phone"
    assert isinstance(result0["ok"], bool)
    if result0["ok"] is True:
        assert isinstance(result0["result"], dict)
