from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_tools_v2_get_case_status_does_not_call_gemini(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Gemini helper should not be called for /tools")

    import api_server.vapi.correction_extractor as correction_extractor
    import api_server.vapi.message_classifier as message_classifier
    import api_server.vapi.message_extractor as message_extractor

    monkeypatch.setattr(message_classifier, "_generate_gemini_text", _raise)
    monkeypatch.setattr(message_extractor, "_generate_gemini_text", _raise)
    monkeypatch.setattr(correction_extractor, "_generate_gemini_text", _raise)

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-no-gemini"},
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
    results = response.json()["results"]
    assert results[0]["ok"] is True

