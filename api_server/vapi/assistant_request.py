"""Helper for handling Vapi assistant-request webhook payloads."""

from __future__ import annotations

import logging
from typing import Any

from api_server.models.database_records import CustomerRecord
from api_server.models.inbound_models import InboundArgs
from api_server.server.dependencies import DatabaseClient
from api_server.utils.phone_formatting import normalize_us_phone_number

logger = logging.getLogger(__name__)

SQUAD_ID = "52cd942d-f789-405c-bd1c-50fdb2037c29"


def build_assistant_request_response(
    message_payload: dict[str, Any],
    database_client: DatabaseClient,
) -> dict[str, Any]:
    if not _is_assistant_request(message_payload):
        return {}

    caller_phone = _get_caller_phone_number(message_payload)
    if caller_phone is None:
        return _build_response(customer=None, caller_phone="")

    try:
        customer_record = _lookup_customer_by_phone(caller_phone, database_client)
    except Exception:
        logger.exception("assistant_request_customer_lookup_failed")
        return _build_response(customer=None, caller_phone=caller_phone)

    return _build_response(customer=customer_record, caller_phone=caller_phone)


def _is_assistant_request(message_payload: dict[str, Any]) -> bool:
    return message_payload.get("type") == "assistant-request"


def _get_caller_phone_number(message_payload: dict[str, Any]) -> str | None:
    call_payload = message_payload.get("call")
    if isinstance(call_payload, dict):
        call_customer = call_payload.get("customer")
        if isinstance(call_customer, dict):
            number = call_customer.get("number")
            if isinstance(number, str):
                stripped = number.strip()
                if stripped:
                    return stripped

    customer_payload = message_payload.get("customer")
    if isinstance(customer_payload, dict):
        number = customer_payload.get("number")
        if isinstance(number, str):
            stripped = number.strip()
            if stripped:
                return stripped

    return None


def _lookup_customer_by_phone(
    caller_phone: str,
    database_client: DatabaseClient,
) -> CustomerRecord | None:
    normalized_phone = normalize_us_phone_number(caller_phone)
    phone_for_lookup = normalized_phone or caller_phone
    inbound_args = InboundArgs(phone_number=phone_for_lookup)
    return database_client.find_customer_by_phone_number(inbound_args)


def _string_or_empty(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _build_response(customer: CustomerRecord | None, caller_phone: str) -> dict[str, Any]:
    is_known = customer is not None
    return {
        "squadId": SQUAD_ID,
        "squadOverrides": {
            "variableValues": {
                "customerName": _string_or_empty(customer.customer_name) if is_known else "",
                "customerPhone": _string_or_empty(caller_phone),
                "customerId": _string_or_empty(customer.customer_id) if is_known else "",
                "companyName": _string_or_empty(customer.company_name) if is_known else "",
                "isKnownCustomer": "true" if is_known else "false",
            }
        },
    }
