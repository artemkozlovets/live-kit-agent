from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_tools_v2_gemini_env_flags_do_not_reenable_network_calls(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")
    monkeypatch.setenv("GET_CASE_STATUS_GEMINI_EXTRACTION", "1")

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Gemini helper should not be called for /tools even if env flag is set")

    import api_server.vapi.message_extractor as message_extractor

    monkeypatch.setattr(message_extractor, "_generate_gemini_text", _raise)

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-env-flags-ignored"},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status",
                "name": "get_case_status",
                "arguments": {"last_user_message": "hello", "expected_field": None},
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    assert response.json()["results"][0]["ok"] is True

