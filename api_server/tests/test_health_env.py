"""'/health/env' exposes env presence without secrets."""

from fastapi.testclient import TestClient


def test_health_env_flags() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)
    response = client.get("/health/env")
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {
        "tools_token_configured",
        "database_url_configured",
        "session_reports_token_configured",
        "local_observability_enabled",
    }
    assert all(isinstance(value, bool) for value in data.values())
