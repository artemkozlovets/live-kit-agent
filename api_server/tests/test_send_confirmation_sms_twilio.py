import os

import pytest
from fastapi.testclient import TestClient


def _set_twilio_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_SMS_FROM_NUMBER", "+15551230000")


def test_send_confirmation_sms_uses_twilio_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_server.integrations.twilio.messages_client import TwilioSendResult

    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")
    _set_twilio_env(monkeypatch)

    async def _fake_send_sms_via_twilio(*_, **__) -> TwilioSendResult:
        return TwilioSendResult(
            message_sid="SM_test_success",
            status="queued",
            error_code=None,
            error_message=None,
        )

    import api_server.vapi.handlers.phone as phone_handler

    monkeypatch.setattr(phone_handler, "send_sms_via_twilio", _fake_send_sms_via_twilio)

    v2_payload = {
        "call": {"id": "call-send-confirmation-sms-twilio-success"},
        "tool_calls": [
            {
                "id": "tool-call-send-confirmation-sms",
                "name": "send_confirmation_sms",
                "arguments": {"phone_number": "+15551234567", "message": "Thanks, you're booked!"},
            }
        ],
    }

    # Act
    response = test_client.post("/tools", json=v2_payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["results"][0]["ok"] is True
    result = response_data["results"][0]["result"]
    assert result["sent"] is True
    assert result["sms_status"] == "queued"
    assert result["message_sid"] == "SM_test_success"


def test_send_confirmation_sms_returns_failed_when_twilio_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_server.integrations.twilio.messages_client import TwilioSendError

    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")
    _set_twilio_env(monkeypatch)

    async def _fake_send_sms_via_twilio(*_, **__) -> object:
        raise TwilioSendError("nope")

    import api_server.vapi.handlers.phone as phone_handler

    monkeypatch.setattr(phone_handler, "send_sms_via_twilio", _fake_send_sms_via_twilio)

    v2_payload = {
        "call": {"id": "call-send-confirmation-sms-twilio-failure"},
        "tool_calls": [
            {
                "id": "tool-call-send-confirmation-sms",
                "name": "send_confirmation_sms",
                "arguments": {"phone_number": "+15551234567", "message": "Thanks, you're booked!"},
            }
        ],
    }

    # Act
    response = test_client.post("/tools", json=v2_payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["results"][0]["ok"] is True
    result = response_data["results"][0]["result"]
    assert result == {
        "sent": False,
        "sms_status": "failed",
        "error": "nope",
        "next_action": "SMS failed to send. Continue without texting and end the call politely.",
    }


def test_twilio_status_callback_requires_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)
    monkeypatch.setenv("TWILIO_WEBHOOK_TOKEN", "secret-token")

    # Act
    resp = test_client.post("/twilio/status-callback", data={"MessageSid": "SM_ignored"})

    # Assert
    assert resp.status_code == 401


def test_twilio_status_callback_updates_store(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from api_server.integrations.twilio.sms_message_store import sms_message_store
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)
    monkeypatch.delenv("TWILIO_WEBHOOK_TOKEN", raising=False)

    # Act
    resp = test_client.post(
        "/twilio/status-callback",
        data={
            "MessageSid": "SM_test_callback",
            "MessageStatus": "delivered",
            "ErrorCode": "",
            "ErrorMessage": "",
            "To": "+15551234567",
            "From": "+15551230000",
        },
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    stored = sms_message_store.get("SM_test_callback")
    assert stored is not None
    assert stored["status"] == "delivered"

