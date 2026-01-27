"""'/health/env' exposes env presence without secrets."""

from fastapi.testclient import TestClient


def test_health_env_flags() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)
    response = client.get("/health/env")
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {
        "google_api_key_loaded",
        "gemini_api_key_loaded",
        "gemini_guard_api_key_loaded",
    }
    assert all(isinstance(value, bool) for value in data.values())
