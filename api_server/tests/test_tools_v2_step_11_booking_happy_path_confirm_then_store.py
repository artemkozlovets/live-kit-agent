from __future__ import annotations

from fastapi.testclient import TestClient

from api_server.models.database_records import UnitForServiceOrderRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self) -> None:
        self.created = 0

    def customer_exists(self, store_service_order_args) -> bool:
        _ = store_service_order_args
        return True

    def find_unit_for_service_order(self, store_service_order_args):
        return UnitForServiceOrderRecord(unit_id=store_service_order_args.unit_id, customer_id="CUST-123")

    def create_service_order(self, store_service_order_args):
        _ = store_service_order_args
        self.created += 1
        return f"SO-{self.created}"


def test_tools_v2_confirm_services_then_store_service_order_succeeds(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-tools-v2-confirm-then-store"
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
        },
    )

    fake_db = FakeDatabaseClient()
    app.dependency_overrides[get_database_client] = lambda: fake_db
    try:
        client = TestClient(app)
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {"id": "tool-call-confirm", "name": "confirm_services", "arguments": {}},
                {"id": "tool-call-store", "name": "store_service_order", "arguments": {}},
            ],
        }

        # Act
        response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
    finally:
        app.dependency_overrides.pop(get_database_client, None)

    # Assert
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is True
    assert results[1]["result"]["order_ids"] == ["SO-1"]

