"""get_case_status: extraction fallback behaviors.

Big picture:
- `get_case_status` runs in the critical path of the voice loop.
- Gemini extraction can fail (timeouts / invalid JSON). When it does, we still
  want to persist *some* useful structured fields so the agent can move forward.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def _post_get_case_status(*, client: TestClient, call_id: str, last_user_message: str) -> dict:
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tool-call-get-case-status",
                    "function": {
                        "name": "get_case_status",
                        "arguments": json.dumps({"call_id": call_id, "last_user_message": last_user_message}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }
    response = client.post("/vapi/tools", json=payload)
    assert response.status_code == 200
    return json.loads(response.json()["results"][0]["result"])


def test_get_case_status_falls_back_to_fast_extractor_when_gemini_returns_none(monkeypatch) -> None:
    """Expected use: Gemini returns None; we still extract deterministically."""
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    monkeypatch.setenv("GET_CASE_STATUS_FAST_EXTRACTOR", "1")

    called_fast = {"value": False}

    async def fake_gemini_extractor(message: str):  # noqa: ANN001
        _ = message
        return None

    def fake_fast_extractor(message: str):  # noqa: ANN001
        assert "Johnson" in message
        called_fast["value"] = True
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

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_gemini_extractor)
    monkeypatch.setattr(case_status_handler, "extract_customer_service_info_fast", fake_fast_extractor)

    call_id = "call-get-case-status-fallback-fast-extractor"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        parsed_result = _post_get_case_status(
            client=client,
            call_id=call_id,
            last_user_message="My last name is Johnson.",
        )

        assert called_fast["value"] is True
        assert parsed_result["customer"]["last_name"] == "Johnson"
        assert parsed_result["missing_fields"] == ["first_name", "phone"]
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_vehicle_description_is_saved_as_unit_nickname(monkeypatch) -> None:
    """Edge case: callers give a vehicle description instead of a VIN/unit number."""
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    call_id = "call-get-case-status-vehicle-description"
    session_store.set(
        call_id,
        {
            "first_name": "John",
            "last_name": "Smith",
            "phone_number": "+15551230000",
        },
    )

    async def fake_extractor(message: str):  # noqa: ANN001
        assert isinstance(message, str)
        return {
            "customer": {
                "first_name": None,
                "last_name": None,
                "phone": None,
                "company": None,
            },
            "service": {
                "location": None,
                "complaint": None,
                "unit_number": None,
                "vin": None,
                "vehicle_description": "Blue truck",
            },
        }

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", fake_extractor)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        client = TestClient(app)
        parsed_result = _post_get_case_status(
            client=client,
            call_id=call_id,
            last_user_message="It's a blue truck.",
        )

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["missing_fields"] == ["location", "complaint"]
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "Where is the vehicle located?"
        assert parsed_result["then_action"] == ""
    finally:
        app.dependency_overrides.pop(get_database_client, None)

