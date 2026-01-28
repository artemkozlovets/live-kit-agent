from __future__ import annotations

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class _FailingDatabaseClient:
    def __getattr__(self, name: str):  # pragma: no cover
        raise AssertionError(f"DB client should not be called (attempted {name})")


def test_tools_v2_store_service_order_requires_explicit_confirmation(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-tools-v2-booking-requires-confirmation"
    session_store.set(
        call_id,
        {
            "customer_id": "CUST-123",
            "services": [
                {
                    "unit_id": "UNIT-1",
                    "service_complaint": "flat tire",
                    "service_location": "Denver CO",
                }
            ],
            # services_confirmed is intentionally missing/false
        },
    )

    app.dependency_overrides[get_database_client] = lambda: _FailingDatabaseClient()
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-store-service-order",
                    "name": "store_service_order",
                    "arguments": {},
                }
            ],
        }

        # Act
        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
    finally:
        app.dependency_overrides.pop(get_database_client, None)

    # Assert
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert result["error"]["code"] == "booking_not_confirmed"

