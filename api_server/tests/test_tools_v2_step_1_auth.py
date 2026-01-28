from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_missing_token_returns_401(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-missing-token"},
        "customer": {"number": "+15551234567"},
        "assistant": {"variable_values": {}},
        "tool_calls": [
            {
                "id": "tool-call-1",
                "name": "validate_phone",
                "arguments": {"phone_number": "305-317-9840"},
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload)

    # Assert
    assert response.status_code == 401
    data = response.json()
    assert isinstance(data, dict)
    assert data.get("detail")

