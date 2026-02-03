"""get_case_status: vehicle identifier prompt policy.

Goal: ask for VIN or make/model at least once, but allow a unit nickname fallback.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def find_customer_by_id(self, customer_id: str):  # noqa: ANN001
        return None


def _post_get_case_status(*, test_client: TestClient, call_id: str, last_user_message: str) -> dict:
    os.environ.setdefault("TOOLS_TOKEN", "test-secret")

    payload = {
        "call": {"id": call_id},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status",
                "name": "get_case_status",
                "arguments": {"last_user_message": last_user_message, "expected_field": None},
            }
        ],
    }

    response = test_client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})
    assert response.status_code == 200
    response_data = response.json()
    return response_data["results"][0]["result"]


def test_get_case_status_service_collection_vehicle_prompt_mentions_vin_and_make_model() -> None:
    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-vehicle-id-prompt"
    session_store.set(
        call_id,
        {
            "first_name": "Pat",
            "last_name": "Lee",
            "phone_number": "+15551230000",
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            last_user_message="I have a flat tire.",
        )

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == (
            "What's the vehicle's VIN? If you don't have it, the make and model are fine — "
            "otherwise a unit number or nickname works too."
        )
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_get_case_status_service_collection_vehicle_prompt_fallback_after_vin_attempts() -> None:
    """After VIN validation failures, stop asking for VIN and accept nickname."""

    from api_server.server.fastapi_app import app
    from api_server.vapi.router import session_store

    call_id = "call-vehicle-id-prompt-fallback"
    session_store.set(
        call_id,
        {
            "first_name": "Pat",
            "last_name": "Lee",
            "phone_number": "+15551230000",
            "vin_attempts": 3,
        },
    )

    app.dependency_overrides[get_database_client] = lambda: FakeDatabaseClient()
    try:
        test_client = TestClient(app)
        parsed_result = _post_get_case_status(
            test_client=test_client,
            call_id=call_id,
            last_user_message="I don't know the VIN.",
        )

        assert parsed_result["current_phase"] == "service_collection"
        assert parsed_result["response_mode"] == "speak_first"
        assert parsed_result["immediate_message"] == "No worries — what's the unit number or a nickname for the vehicle?"
    finally:
        app.dependency_overrides.pop(get_database_client, None)

