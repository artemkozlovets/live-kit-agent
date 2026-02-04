"""Session-related Vapi tool handlers (in-memory accumulation)."""

from __future__ import annotations

from typing import Any

from api_server.server.dependencies import DatabaseClient
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_call_id, parse_tool_arguments


MAX_SERVICES_PER_CALL = 5


def handle_add_service(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = database_client
    service_data = parse_tool_arguments(tool_call)

    vehicle_identifier_type_raw = service_data.get("vehicle_identifier_type")
    vehicle_identifier_raw = service_data.get("vehicle_identifier")
    if isinstance(vehicle_identifier_type_raw, str) and isinstance(vehicle_identifier_raw, str):
        vehicle_identifier_type = vehicle_identifier_type_raw.strip().lower()
        vehicle_identifier = vehicle_identifier_raw.strip()
        if vehicle_identifier_type and vehicle_identifier:
            if vehicle_identifier_type in {"vin", "vin_number"}:
                service_data.setdefault("vin_number", vehicle_identifier)
            elif vehicle_identifier_type in {"unit_number", "unit"}:
                service_data.setdefault("unit_number", vehicle_identifier)
            elif vehicle_identifier_type in {"unit_nickname", "nickname"}:
                service_data.setdefault("unit_nickname", vehicle_identifier)

        # Reason: Keep stored service data aligned with backend expectations.
        service_data.pop("vehicle_identifier_type", None)
        service_data.pop("vehicle_identifier", None)

    # Reason: Must have at least one vehicle identifier.
    has_vehicle_id = any(
        service_data.get(key) for key in ("vin_number", "unit_number", "unit_nickname")
    )
    if not has_vehicle_id:
        return {
            "added": False,
            "error": "Vehicle ID required",
            "next_action": "Ask caller for VIN, unit number, or vehicle nickname before adding service.",
        }

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    services = session.get("services", [])
    if not isinstance(services, list):
        services = []

    # Reason: Cap at 5 services to prevent abuse.
    if len(services) >= MAX_SERVICES_PER_CALL:
        return {
            "added": False,
            "error": "Maximum 5 services per call",
            "next_action": "Limit reached. Ask if caller wants to finalize current services or call back for more.",
        }

    services.append(service_data)
    session["services"] = services
    # Reason: Reset VIN attempts for the next vehicle.
    session["vin_attempts"] = 0
    session_store.set(call_id, session)

    # Reason: Guide assistant to ask about additional services or finalize
    return {
        "added": True,
        "service_count": len(services),
        "next_action": "Service added. Ask caller if they need service for another vehicle, or proceed to finalize the order.",
    }


def handle_get_session_summary(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = tool_call
    _ = database_client
    call_id = get_call_id(message_payload)

    session = session_store.get(call_id)
    services = session.get("services", [])
    if not isinstance(services, list):
        services = []

    # Reason: Add vehicle_id_type so callers can see which identifier was used.
    formatted_services: list[dict[str, Any]] = []
    for service in services:
        if not isinstance(service, dict):
            continue

        formatted_service = dict(service)
        if formatted_service.get("vin_number"):
            formatted_service["vehicle_id_type"] = "vin"
        elif formatted_service.get("unit_number"):
            formatted_service["vehicle_id_type"] = "unit_number"
        elif formatted_service.get("unit_nickname"):
            formatted_service["vehicle_id_type"] = "unit_nickname"

        formatted_services.append(formatted_service)

    # Reason: Guide assistant to finalize order after reviewing summary
    return {
        "service_count": len(formatted_services),
        "services": formatted_services,
        "services_confirmed": session.get("services_confirmed", False),
        "next_action": (
            "Review services with caller. If the caller confirms, call confirm_services, then call store_service_order to finalize."
        ),
    }


def handle_confirm_services(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = tool_call
    _ = database_client
    call_id = get_call_id(message_payload)
    if not call_id:
        return {"confirmed": False, "error": "Missing call id"}

    session = session_store.get(call_id)
    customer_id = session.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        return {
            "confirmed": False,
            "error": "Customer data required",
            "next_action": (
                "Customer not identified. Call handoff_to_CustomerIntake "
                "to collect customer details."
            ),
        }

    session["services_confirmed"] = True
    session_store.set(call_id, session)
    return {
        "confirmed": True,
        "next_action": "Services confirmed. Handoff to Booking.",
    }
