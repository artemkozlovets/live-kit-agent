"""Vehicle-related Vapi tool handlers."""

from __future__ import annotations

from typing import Any

from api_server.models.check_vin_models import CheckVinArgs
from api_server.server.dependencies import DatabaseClient
from api_server.utils.vin_formatting import VIN_NUMBER_REGEX, normalize_vin_number
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_call_id, parse_tool_arguments


MAX_VIN_VALIDATION_ATTEMPTS = 3


def _get_vin_from_tool_arguments(tool_arguments: dict[str, Any]) -> str | None:
    vin_number = tool_arguments.get("vin_number")
    if isinstance(vin_number, str) and vin_number:
        return vin_number

    vin = tool_arguments.get("vin")
    if isinstance(vin, str) and vin:
        return vin

    return None


def handle_validate_vin(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = database_client
    tool_arguments = parse_tool_arguments(tool_call)
    vin_number = _get_vin_from_tool_arguments(tool_arguments)
    cleaned_vin_number = normalize_vin_number(vin_number) if vin_number is not None else ""

    is_vin_format_valid = bool(VIN_NUMBER_REGEX.fullmatch(cleaned_vin_number))
    if is_vin_format_valid:
        # Reason: Guide assistant to check if VIN exists in customer's fleet
        return {
            "valid": True,
            "decoded": {"vin": cleaned_vin_number},
            "next_action": f"Immediately call check_vin_database with vin_number={cleaned_vin_number}. Do not wait for user input.",
        }

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    attempt_number = int(session.get("vin_attempts", 0)) + 1
    session["vin_attempts"] = attempt_number
    session_store.set(call_id, session)

    result: dict[str, Any] = {
        "valid": False,
        "attempt": attempt_number,
        "max_attempts": MAX_VIN_VALIDATION_ATTEMPTS,
        "next_action": "Ask the caller to provide the 17-character VIN again.",
    }

    # Reason: After 3 attempts, allow fallback to unit_number/unit_nickname.
    if attempt_number >= MAX_VIN_VALIDATION_ATTEMPTS:
        result["fallback"] = ["unit_number", "unit_nickname"]
        result["next_action"] = "Max attempts reached. Ask for unit number or vehicle nickname instead."

    return result


def handle_check_vin_database(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = message_payload
    _ = session_store
    tool_arguments = parse_tool_arguments(tool_call)
    vin_number = _get_vin_from_tool_arguments(tool_arguments)
    cleaned_vin_number = normalize_vin_number(vin_number) if vin_number is not None else ""

    is_vin_format_valid = bool(VIN_NUMBER_REGEX.fullmatch(cleaned_vin_number))
    if not is_vin_format_valid:
        return {
            "vin_number": cleaned_vin_number,
            "is_in_database": False,
            "next_action": "VIN format invalid. Ask caller for unit number or vehicle nickname instead.",
        }

    check_vin_args = CheckVinArgs(vin_number=cleaned_vin_number)
    unit_record = database_client.find_unit_by_vin_number(check_vin_args)
    if unit_record is None:
        # Reason: VIN not in database - will be auto-created when service order is stored
        return {
            "vin_number": cleaned_vin_number,
            "unit_number": "",
            "is_in_database": False,
            "next_action": "VIN not found in fleet. Proceed to collect service details with add_service.",
        }

    # Reason: Guide assistant to proceed with service collection
    return {
        "vin_number": cleaned_vin_number,
        "unit_number": unit_record.unit_number,
        "is_in_database": True,
        "next_action": "Vehicle found. Proceed to collect service details with add_service.",
    }
