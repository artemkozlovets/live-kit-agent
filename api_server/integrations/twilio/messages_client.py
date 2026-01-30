from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwilioSmsConfig:
    account_sid: str
    auth_token: str
    from_number: str | None
    messaging_service_sid: str | None
    status_callback_url: str | None


@dataclass(frozen=True)
class TwilioSendResult:
    message_sid: str
    status: str | None
    error_code: int | None
    error_message: str | None


class TwilioSendError(RuntimeError):
    """Raised when Twilio rejects or fails a send attempt."""


def load_twilio_sms_config() -> TwilioSmsConfig | None:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_SMS_FROM_NUMBER", "").strip()
    messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
    status_callback_url = os.getenv("TWILIO_STATUS_CALLBACK_URL", "").strip()

    if not account_sid or not auth_token:
        return None

    from_number_value = from_number or None
    messaging_service_sid_value = messaging_service_sid or None
    if from_number_value is None and messaging_service_sid_value is None:
        return None

    return TwilioSmsConfig(
        account_sid=account_sid,
        auth_token=auth_token,
        from_number=from_number_value,
        messaging_service_sid=messaging_service_sid_value,
        status_callback_url=status_callback_url or None,
    )


def _safe_error_message(payload: object) -> str:
    """Return a short error string without including PII."""

    if not isinstance(payload, dict):
        return "Twilio request failed"

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()

    code = payload.get("code")
    if isinstance(code, (int, str)):
        return f"Twilio request failed (code={code})"

    return "Twilio request failed"


async def send_sms_via_twilio(
    *,
    config: TwilioSmsConfig,
    to_number: str,
    body: str,
) -> TwilioSendResult:
    """Send an SMS using Twilio's Messages API.

    Notes:
    - Uses HTTP basic auth (Account SID + Auth Token).
    - Uses either `From` or `MessagingServiceSid`.
    - Optional `StatusCallback` can be set via env for delivery tracking.
    """

    return await asyncio.to_thread(
        _send_sms_via_twilio_sync,
        config=config,
        to_number=to_number,
        body=body,
    )

def _send_sms_via_twilio_sync(
    *,
    config: TwilioSmsConfig,
    to_number: str,
    body: str,
) -> TwilioSendResult:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.account_sid}/Messages.json"
    data: dict[str, str] = {
        "To": to_number,
        "Body": body,
    }

    if config.status_callback_url:
        data["StatusCallback"] = config.status_callback_url

    if config.messaging_service_sid:
        data["MessagingServiceSid"] = config.messaging_service_sid
    elif config.from_number:
        data["From"] = config.from_number

    encoded = urllib.parse.urlencode(data).encode("utf-8")

    auth_raw = f"{config.account_sid}:{config.auth_token}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", response.getcode()))
    except urllib.error.HTTPError as exc:
        status_code = int(getattr(exc, "code", 0) or 0)
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
            payload: Any = json.loads(error_body)
        except Exception:
            payload = None
        logger.warning("Twilio HTTP error", extra={"status_code": status_code})
        raise TwilioSendError(_safe_error_message(payload)) from exc
    except urllib.error.URLError as exc:
        raise TwilioSendError("Twilio request failed") from exc

    if status_code >= 400:
        raise TwilioSendError(f"Twilio request failed (status={status_code})")

    try:
        payload: Any = json.loads(response_body)
    except Exception as exc:
        logger.warning("Twilio response was not JSON", extra={"status_code": status_code})
        raise TwilioSendError("Twilio returned an invalid response") from exc

    if not isinstance(payload, dict):
        raise TwilioSendError("Twilio returned an invalid response")

    sid = payload.get("sid")
    if not isinstance(sid, str) or not sid.strip():
        raise TwilioSendError("Twilio returned an invalid message SID")

    status = payload.get("status")
    status_value = status.strip() if isinstance(status, str) and status.strip() else None

    error_code = payload.get("error_code")
    error_code_value = int(error_code) if isinstance(error_code, int) else None

    error_message = payload.get("error_message")
    error_message_value = (
        error_message.strip() if isinstance(error_message, str) and error_message.strip() else None
    )

    return TwilioSendResult(
        message_sid=sid.strip(),
        status=status_value,
        error_code=error_code_value,
        error_message=error_message_value,
    )
