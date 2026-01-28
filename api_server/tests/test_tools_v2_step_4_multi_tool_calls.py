from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_multiple_tool_calls_return_multiple_correlated_results(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-multi"},
        "tool_calls": [
            {
                "id": "tool-call-1",
                "name": "validate_phone",
                "arguments": {"phone_number": "305-317-9840"},
            },
            {
                "id": "tool-call-2",
                "name": "validate_phone",
                "arguments": {"phone_number": "305-317-9840"},
            },
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    results = response.json()["results"]
    assert isinstance(results, list)
    assert [r["tool_call_id"] for r in results] == ["tool-call-1", "tool-call-2"]

