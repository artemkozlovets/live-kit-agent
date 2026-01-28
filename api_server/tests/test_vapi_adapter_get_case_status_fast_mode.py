"""get_case_status: fast mode wiring (no Gemini network calls)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def test_get_case_status_fast_extractor_runs_when_gemini_disabled(monkeypatch) -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    import api_server.vapi.handlers.case_status as case_status_handler

    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CLASSIFICATION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "0")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_CORRECTIONS", "0")
    monkeypatch.setenv("GET_CASE_STATUS_FAST_EXTRACTOR", "1")

    async def should_not_be_called(message: str):  # noqa: ANN001
        raise AssertionError("Gemini extractor should not be called when GET_CASE_STATUS_GEMINI_EXTRACTION=0")

    monkeypatch.setattr(case_status_handler, "extract_customer_service_info", should_not_be_called)

    call_id = "call-get-case-status-fast-mode"
    session_store.clear(call_id)

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        token = "test-secret"
        previous_token = os.environ.get("TOOLS_TOKEN")
        os.environ["TOOLS_TOKEN"] = token
        payload = {
            "call": {"id": call_id},
            "tool_calls": [
                {
                    "id": "tool-call-get-case-status-fast-mode",
                    "name": "get_case_status",
                    "arguments": {
                        "call_id": call_id,
                        "last_user_message": "My last name is Johnson.",
                    },
                }
            ],
        }

        response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": token})
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["results"][0]["ok"] is True
        parsed_result = response_data["results"][0]["result"]

        assert parsed_result["customer"]["last_name"] == "Johnson"
        assert parsed_result["missing_fields"] == ["first_name", "phone"]
    finally:
        if previous_token is None:
            os.environ.pop("TOOLS_TOKEN", None)
        else:
            os.environ["TOOLS_TOKEN"] = previous_token
        app.dependency_overrides.pop(get_database_client, None)
