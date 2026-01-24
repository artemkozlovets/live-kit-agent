"""Phone-related Vapi tool handlers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from api_server.models.inbound_models import InboundArgs
from api_server.models.new_customer_models import NewCustomerArgs
from api_server.server.dependencies import DatabaseClient
from api_server.utils.phone_formatting import normalize_us_phone_number
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_call_id, parse_tool_arguments


MAX_PHONE_VALIDATION_ATTEMPTS = 3


def _get_last_four_digits(phone_number: str) -> str | None:
    # Reason: Compare phone numbers without storing/logging the full number (PII).
    digits_only = re.sub(r"\D", "", phone_number or "")
    return digits_only[-4:] if len(digits_only) >= 4 else None


def _get_customer_number_from_message_payload(message_payload: dict[str, Any]) -> str | None:
    """
    Return the caller's number from Vapi's message payload (if present).

    Reason: For phone calls, Vapi includes the caller ID as `message.customer.number`
    and also under `message.call.customer.number`. When the model passes a malformed
    number into `validate_phone`, we can safely fall back to the caller ID (when it
    matches by last 4 digits).
    """
    customer_payload = message_payload.get("customer")
    if isinstance(customer_payload, dict):
        number = customer_payload.get("number")
        if isinstance(number, str) and number:
            return number

    call_payload = message_payload.get("call")
    if isinstance(call_payload, dict):
        call_customer = call_payload.get("customer")
        if isinstance(call_customer, dict):
            number = call_customer.get("number")
            if isinstance(number, str) and number:
                return number

    return None


def _split_contact_name(customer_name: str) -> tuple[str | None, str | None]:
    # Reason: Preserve missing name parts when only first or last name is updated.
    parts = customer_name.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _normalize_name_part(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _build_contact_name(
    existing_name: str,
    first_name: str | None,
    last_name: str | None,
) -> str:
    existing_first, existing_last = _split_contact_name(existing_name)
    new_first = first_name if first_name is not None else existing_first
    new_last = last_name if last_name is not None else existing_last
    return " ".join(part for part in (new_first, new_last) if part)


NEW_CUSTOMER_REQUIRED_FIELDS: list[str] = [
    "first_name",
    "last_name",
    "company_name",
    "email_address",
    "streetAddress",
    "city",
    "state",
    "postalCode",
]


def _get_missing_new_customer_fields(known_data: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []
    for field_name in NEW_CUSTOMER_REQUIRED_FIELDS:
        value = known_data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            missing_fields.append(field_name)
    return missing_fields


def handle_validate_phone(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = database_client
    tool_arguments = parse_tool_arguments(tool_call)
    phone_number = tool_arguments.get("phone_number")

    normalized_phone_number = (
        normalize_us_phone_number(phone_number) if isinstance(phone_number, str) else None
    )

    # Reason: We instruct the model to use `{{customer.number}}` when available.
    # In practice, the model sometimes passes a malformed string (extra digits) to
    # validate_phone even though Vapi provided the correct caller ID in the payload.
    if normalized_phone_number is None:
        caller_number = _get_customer_number_from_message_payload(message_payload)

        if isinstance(caller_number, str) and caller_number:
            if not isinstance(phone_number, str):
                # Reason: If the model didn't send a number at all, use caller ID.
                normalized_phone_number = normalize_us_phone_number(caller_number)
            else:
                phone_last4 = _get_last_four_digits(phone_number)
                caller_last4 = _get_last_four_digits(caller_number)

                # Reason: Only fall back when it's clearly the same number (avoid
                # overriding a caller-provided alternate contact number).
                if phone_last4 and caller_last4 and phone_last4 == caller_last4:
                    normalized_phone_number = normalize_us_phone_number(caller_number)

    if normalized_phone_number is not None:
        # Reason: Guide the assistant to immediately proceed to customer lookup
        return {
            "valid": True,
            "is_mobile": False,
            "formatted": normalized_phone_number,
            "next_action": f"Immediately call check_customer with phone_number={normalized_phone_number}. Do not wait for user input.",
        }

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    attempt_number = int(session.get("phone_attempts", 0)) + 1
    session["phone_attempts"] = attempt_number
    session_store.set(call_id, session)

    result: dict[str, Any] = {
        "valid": False,
        "attempt": attempt_number,
        "max_attempts": MAX_PHONE_VALIDATION_ATTEMPTS,
        "error": "Invalid phone number format",
        "next_action": "Ask the caller to provide a valid 10-digit US phone number.",
    }

    if attempt_number >= MAX_PHONE_VALIDATION_ATTEMPTS:
        result["proceed_unvalidated"] = True
        # Reason: After max attempts, proceed anyway to avoid frustrating the caller
        result["next_action"] = "Max attempts reached. Proceed to check_customer with the phone number as-is."

    return result


def handle_check_customer(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    tool_arguments = parse_tool_arguments(tool_call)
    phone_number = tool_arguments.get("phone_number")
    known_data = tool_arguments.get("known_data")
    known_data_dict = known_data if isinstance(known_data, dict) else {}
    missing_fields = _get_missing_new_customer_fields(known_data_dict)

    if not isinstance(phone_number, str) or not phone_number:
        return {
            "found": False,
            "next_action_fields": missing_fields,
            "next_action": (
                "Collect any missing customer details (do not re-ask details already provided earlier in the call): "
                f"{', '.join(missing_fields)}. "
                "Then call register_new_customer."
            ),
        }

    normalized_phone_number = normalize_us_phone_number(phone_number)
    phone_number_for_lookup = normalized_phone_number or phone_number

    inbound_args = InboundArgs(phone_number=phone_number_for_lookup)
    customer_record = database_client.find_customer_by_phone_number(inbound_args)
    if customer_record is None:
        # Reason: Guide assistant to collect only the missing info for new customer registration.
        if missing_fields:
            return {
                "found": False,
                "next_action_fields": missing_fields,
                "next_action": (
                    "No customer found. Collect any missing customer details (do not re-ask details already provided earlier in the call): "
                    f"{', '.join(missing_fields)}. "
                    "Then call register_new_customer."
                ),
            }

        return {
            "found": False,
            "ready_to_register": True,
            "next_action_fields": [],
            "next_action": (
                "No customer found, but all required customer fields are already collected. "
                "Immediately call register_new_customer now."
            ),
        }

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    session["customer_id"] = customer_record.customer_id
    session["customer_registered"] = True
    session_store.set(call_id, session)

    # Reason: Guide assistant to greet returning customer and proceed to service
    return {
        "found": True,
        "customer": {
            "customer_id": customer_record.customer_id,
            "customer_name": customer_record.customer_name,
            "phone_number": customer_record.phone_number,
        },
        "next_action": f"Greet {customer_record.customer_name} by name and proceed to service collection. Call handoff_to_ServiceCollection.",
    }


def handle_register_new_customer(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    tool_arguments = parse_tool_arguments(tool_call)
    try:
        new_customer_args = NewCustomerArgs(**tool_arguments)
    except ValidationError:
        return {"error": "Invalid register_new_customer arguments"}

    normalized_phone_number = normalize_us_phone_number(new_customer_args.phone_number)
    if normalized_phone_number is None:
        return {"error": "Invalid phone number"}

    new_customer_args_with_normalized_phone_number = new_customer_args.model_copy(
        update={"phone_number": normalized_phone_number}
    )

    customer_id = database_client.create_customer(new_customer_args_with_normalized_phone_number)

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    session["customer_id"] = customer_id
    session["customer_registered"] = True
    session_store.set(call_id, session)

    # Reason: Guide assistant to proceed to service collection after registration
    return {
        "customer_id": customer_id,
        "next_action": "Customer registered. Proceed to service collection. Call handoff_to_ServiceCollection.",
    }


def handle_update_customer(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    tool_arguments = parse_tool_arguments(tool_call)
    updates = tool_arguments.get("updates")
    updates_dict = updates if isinstance(updates, dict) else {}

    phone_number = tool_arguments.get("phone_number")
    customer_id = tool_arguments.get("customer_id")

    customer_record = None
    if isinstance(customer_id, str) and customer_id:
        customer_record = database_client.find_customer_by_id(customer_id)
    else:
        phone_number_for_lookup = None
        if isinstance(phone_number, str) and phone_number:
            normalized_phone_number = normalize_us_phone_number(phone_number)
            phone_number_for_lookup = normalized_phone_number or phone_number

        if phone_number_for_lookup:
            inbound_args = InboundArgs(phone_number=phone_number_for_lookup)
            customer_record = database_client.find_customer_by_phone_number(inbound_args)
        else:
            call_id = get_call_id(message_payload)
            session = session_store.get(call_id)
            session_customer_id = session.get("customer_id")
            if isinstance(session_customer_id, str) and session_customer_id:
                customer_record = database_client.find_customer_by_id(session_customer_id)
                customer_id = session_customer_id
            else:
                return {
                    "success": False,
                    "error": "No customer identifier provided",
                    "next_action": "Ask caller to confirm their phone number.",
                }

    if customer_record is None:
        return {
            "success": False,
            "error": "Customer not found",
            "next_action": "Customer not found in system. May need to register first.",
        }

    updates_for_db = dict(updates_dict)
    first_name = _normalize_name_part(updates_dict.get("first_name"))
    last_name = _normalize_name_part(updates_dict.get("last_name"))
    if first_name is not None or last_name is not None:
        # Reason: DB stores a single contact_name; preserve missing parts.
        updates_for_db["contact_name"] = _build_contact_name(
            customer_record.customer_name,
            first_name,
            last_name,
        )

    if "phone_number" in updates_dict:
        updated_phone = updates_dict.get("phone_number")
        if isinstance(updated_phone, str) and updated_phone:
            normalized_updated_phone = normalize_us_phone_number(updated_phone)
            if normalized_updated_phone is None:
                return {
                    "success": False,
                    "error": "Invalid phone number",
                    "next_action": "Ask caller to confirm their phone number.",
                }
            updates_for_db["phone_number"] = normalized_updated_phone
        else:
            updates_for_db.pop("phone_number", None)

    updated_customer_id = database_client.update_customer(
        customer_record.customer_id,
        updates_for_db,
    )
    if updated_customer_id is None:
        return {
            "success": False,
            "error": "Customer not found",
            "next_action": "Customer not found in system. May need to register first.",
        }

    updated_fields = [
        field for field, value in updates_dict.items() if value is not None
    ]

    call_id = get_call_id(message_payload)
    if call_id:
        session = session_store.get(call_id)
        session["customer_id"] = customer_record.customer_id
        session["customer_registered"] = True
        if "phone_number" in updates_for_db:
            session["phone_number"] = updates_for_db["phone_number"]
        session["current_phase"] = "completed"
        session.pop("pending_correction", None)
        session_store.set(call_id, session)

    return {
        "success": True,
        "updated_fields": updated_fields,
        "customer_id": customer_record.customer_id,
        "next_action": "Customer information updated. Continue with the call.",
    }


def handle_send_confirmation_sms(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = tool_call
    _ = message_payload
    _ = session_store
    _ = database_client
    # Reason: SMS is not configured, but order is complete - guide assistant to wrap up
    return {
        "sent": False,
        "sms_status": "not_configured",
        "next_action": "SMS skipped (not configured). Thank the caller, confirm help is on the way, and end the call politely.",
    }
