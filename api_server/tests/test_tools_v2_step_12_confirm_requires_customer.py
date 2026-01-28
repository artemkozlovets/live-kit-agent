from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_confirm_services_requires_customer_id(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-tools-v2-confirm-requires-customer"
    session_store.set(call_id, {"services": [{"unit_id": "UNIT-1"}]})

    client = TestClient(app)
    payload = {
        "call": {"id": call_id},
        "tool_calls": [{"id": "tool-call-confirm", "name": "confirm_services", "arguments": {}}],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert "message" in result["error"]

