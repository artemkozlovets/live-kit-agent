"""get_case_status: resolve call_id from payload, not tool arguments."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def test_get_case_status_uses_payload_call_id_over_tool_args(monkeypatch) -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    call_id = "call-real-id"
    placeholder_call_id = "{{VAPI_CALL_ID}}"
    session_store.clear(call_id)
    session_store.clear(placeholder_call_id)

    async def fake_extractor(message: str):  # noqa: ANN001
        assert isinstance(message, str)
        return {
            "customer": {
                "first_name": None,
                "last_name": "Johnson",
                "phone": None,
                "company": None,
            },
            "service": {
                "location": None,
                "complaint": None,
                "unit_number": None,
                "vin": None,
                "vehicle_description": None,
            },
        }

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_extractor)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        payload = {
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [
                    {
                        "id": "tool-call-get-case-status-call-id",
                        "function": {
                            "name": "get_case_status",
                            "arguments": json.dumps(
                                {
                                    "call_id": placeholder_call_id,
                                    "last_user_message": "My last name is Johnson.",
                                }
                            ),
                        },
                    }
                ],
                "assistant": {"extractedVariables": {}},
            }
        }

        response = test_client.post("/vapi/tools", json=payload)

        assert response.status_code == 200
        assert session_store.get(call_id).get("last_name") == "Johnson"
        assert session_store.get(placeholder_call_id) == {}
    finally:
        app.dependency_overrides.pop(get_database_client, None)
