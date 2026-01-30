from __future__ import annotations

import logging
import os
import urllib.parse

from fastapi import APIRouter, HTTPException, Request, status

from api_server.integrations.twilio.sms_message_store import sms_message_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twilio", tags=["twilio"])


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _require_webhook_token(provided: str | None) -> None:
    expected = os.getenv("TWILIO_WEBHOOK_TOKEN", "").strip()
    if not expected:
        # Reason: Let dev environments run without an extra token, but log so
        # production deploys can choose to enforce it.
        return
    if not provided or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def _parse_urlencoded_body(request: Request) -> dict[str, str]:
    """Parse `application/x-www-form-urlencoded` without python-multipart.

    Reason: Twilio webhooks send urlencoded payloads, but we don't want to require
    the optional `python-multipart` dependency just to parse them.
    """

    body = await request.body()
    if not body:
        return {}

    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        decoded = body.decode("latin-1", errors="replace")

    parsed = urllib.parse.parse_qs(decoded, keep_blank_values=True)
    flattened: dict[str, str] = {}
    for key, values in parsed.items():
        if not isinstance(key, str):
            continue
        if not values:
            continue
        first = values[0]
        if isinstance(first, str):
            flattened[key] = first
    return flattened


@router.post("/status-callback")
async def twilio_status_callback(request: Request) -> dict[str, bool]:
    # Optional defense-in-depth (when configured): require a shared secret.
    _require_webhook_token(request.query_params.get("token"))

    # Twilio sends application/x-www-form-urlencoded by default.
    form = await _parse_urlencoded_body(request)

    message_sid = form.get("MessageSid")
    if not isinstance(message_sid, str) or not message_sid.strip():
        # Reason: Avoid noisy retries; treat missing fields as a no-op.
        logger.warning("Twilio status callback missing MessageSid")
        return {"ok": True}

    message_status = form.get("MessageStatus")
    status_value = message_status.strip() if isinstance(message_status, str) and message_status.strip() else None

    error_code = _optional_int(form.get("ErrorCode"))
    error_message = form.get("ErrorMessage")
    error_message_value = (
        error_message.strip() if isinstance(error_message, str) and error_message.strip() else None
    )

    to_number = form.get("To")
    to_number_value = to_number.strip() if isinstance(to_number, str) and to_number.strip() else None

    from_number = form.get("From")
    from_number_value = from_number.strip() if isinstance(from_number, str) and from_number.strip() else None

    sms_message_store.update_status(
        message_sid=message_sid.strip(),
        status=status_value,
        error_code=error_code,
        error_message=error_message_value,
        to_number=to_number_value,
        from_number=from_number_value,
    )

    return {"ok": True}
