from __future__ import annotations

from fastapi.testclient import TestClient


def test_vapi_tools_removed_returns_404(monkeypatch) -> None:
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    response = client.post("/vapi/tools", json={})
    assert response.status_code == 404

