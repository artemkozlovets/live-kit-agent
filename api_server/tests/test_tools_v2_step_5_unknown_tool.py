from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_unknown_tool_returns_ok_false_with_error(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-unknown-tool"},
        "tool_calls": [
            {
                "id": "tool-call-unknown",
                "name": "definitely_not_a_tool",
                "arguments": {},
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    results = response.json()["results"]
    assert isinstance(results, list)
    assert results[0]["ok"] is False
    error = results[0]["error"]
    assert isinstance(error, dict)
    assert error.get("code")
    assert error.get("message")

