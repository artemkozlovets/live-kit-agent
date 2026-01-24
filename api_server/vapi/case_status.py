"""Pure case-status logic for the `get_case_status` tool (no I/O)."""

from __future__ import annotations

from typing import Any

from api_server.models.database_records import CustomerRecord


def _split_full_name(full_name: str) -> tuple[str | None, str | None]:
    # Reason: Our DB stores a single `contact_name`, but the assistant workflow
    # expects first/last name separately for completeness checks.
    parts = full_name.strip().split() if isinstance(full_name, str) else []
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])

def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _build_empty_case_status(*, next_action: str) -> dict[str, Any]:
    return {
        "customer": {"id": None, "first_name": None, "last_name": None, "phone": None, "email": None, "company": None},
        "service": {"id": None, "vin": None, "unit_number": None, "unit_nickname": None, "location": None, "location_is_safe": None, "is_mobile": None, "complaint": None},
        "booking": {"id": None, "eta": None, "technician": None, "status": None},
        "missing_fields": ["first_name", "last_name", "phone"],
        "current_phase": "customer_intake",
        "ready_for_handoff": {"to_service_collection": False, "to_booking": False},
        "next_action": next_action,
        "validation_state": {"phone_attempts": 0, "vin_attempts": 0, "vin_fallback_triggered": False},
    }


def build_case_status(
    *,
    session: dict[str, Any],
    customer_record: CustomerRecord | None,
) -> dict[str, Any]:
    """Build the get_case_status result object from session + customer record."""
    is_session_empty = not session
    explicit_phase = _normalize_optional_str(session.get("current_phase"))
    customer_registered = bool(session.get("customer_registered", False))

    phone_attempts = _as_int(session.get("phone_attempts", 0))
    vin_attempts = _as_int(session.get("vin_attempts", 0))
    vin_fallback_triggered = vin_attempts >= 3

    if customer_record is None:
        session_customer_id = session.get("customer_id")
        customer_id = (
            session_customer_id
            if customer_registered and isinstance(session_customer_id, str) and session_customer_id
            else None
        )
        first_name = _normalize_optional_str(session.get("first_name"))
        last_name = _normalize_optional_str(session.get("last_name"))
        phone = _normalize_optional_str(session.get("phone_number") or session.get("phone"))
        company = _normalize_optional_str(session.get("company_name") or session.get("company"))

        services = session.get("services", [])
        latest_service = services[-1] if isinstance(services, list) and services else {}
        latest_service_dict = latest_service if isinstance(latest_service, dict) else {}

        service = {
            "id": None,
            "vin": _normalize_optional_str(latest_service_dict.get("vin_number"))
            or _normalize_optional_str(session.get("vin_number")),
            "unit_number": _normalize_optional_str(latest_service_dict.get("unit_number"))
            or _normalize_optional_str(session.get("unit_number")),
            "unit_nickname": _normalize_optional_str(latest_service_dict.get("unit_nickname"))
            or _normalize_optional_str(session.get("unit_nickname")),
            "location": _normalize_optional_str(latest_service_dict.get("service_location"))
            or _normalize_optional_str(session.get("service_location")),
            "location_is_safe": latest_service_dict.get("location_is_safe")
            if isinstance(latest_service_dict.get("location_is_safe"), bool)
            else None,
            "is_mobile": latest_service_dict.get("is_mobile")
            if isinstance(latest_service_dict.get("is_mobile"), bool)
            else None,
            "complaint": _normalize_optional_str(latest_service_dict.get("service_complaint"))
            or _normalize_optional_str(session.get("service_complaint")),
        }

        missing_fields: list[str] = []
        if first_name is None:
            missing_fields.append("first_name")
        if last_name is None:
            missing_fields.append("last_name")
        if phone is None:
            missing_fields.append("phone")

        if first_name is None or last_name is None:
            next_action = (
                "This is a new call. Start by collecting the customer's name."
                if is_session_empty
                else "Start by asking for the customer's name."
            )
        elif phone is None:
            next_action = "Collect the customer's phone number"
        else:
            next_action = (
                "Validate the customer's phone number, then look up or register the customer."
            )

        case_state: dict[str, Any] = {
            "customer": {
                "id": customer_id,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "email": None,
                "company": company,
            },
            "service": service,
            "booking": {
                "id": None,
                "eta": None,
                "technician": None,
                "status": None,
            },
            "missing_fields": missing_fields,
            "current_phase": "customer_intake",
            "ready_for_handoff": {"to_service_collection": False, "to_booking": False},
            "next_action": next_action,
            "validation_state": {
                "phone_attempts": phone_attempts,
                "vin_attempts": vin_attempts,
                "vin_fallback_triggered": vin_fallback_triggered,
            },
        }
        if explicit_phase in {"completed", "correction"} and customer_id is not None:
            # Reason: If we have a registered customer_id but can't fetch the record,
            # keep the call in the explicit phase rather than resetting the flow.
            case_state["current_phase"] = explicit_phase
            case_state["missing_fields"] = []
            case_state["ready_for_handoff"] = {"to_service_collection": False, "to_booking": False}
            if isinstance(case_state.get("booking"), dict):
                case_state["booking"]["status"] = "completed" if explicit_phase == "completed" else case_state["booking"].get("status")
            case_state["next_action"] = (
                "Order completed. If the caller requests an update, collect the corrected value and call update_customer."
                if explicit_phase == "completed"
                else "Collect the corrected value and call update_customer, then return to completed."
            )
        return case_state

    first_name, last_name = _split_full_name(customer_record.customer_name)
    customer = {
        "id": customer_record.customer_id,
        "first_name": first_name,
        "last_name": last_name,
        "phone": _normalize_optional_str(customer_record.phone_number),
        "email": _normalize_optional_str(customer_record.email),
        "company": _normalize_optional_str(customer_record.company_name),
    }

    services = session.get("services", [])
    latest_service = services[-1] if isinstance(services, list) and services else {}
    latest_service_dict = latest_service if isinstance(latest_service, dict) else {}

    service = {
        "id": None,
        "vin": _normalize_optional_str(latest_service_dict.get("vin_number"))
        or _normalize_optional_str(session.get("vin_number")),
        "unit_number": _normalize_optional_str(latest_service_dict.get("unit_number"))
        or _normalize_optional_str(session.get("unit_number")),
        "unit_nickname": _normalize_optional_str(latest_service_dict.get("unit_nickname"))
        or _normalize_optional_str(session.get("unit_nickname")),
        "location": _normalize_optional_str(latest_service_dict.get("service_location"))
        or _normalize_optional_str(session.get("service_location")),
        "location_is_safe": latest_service_dict.get("location_is_safe")
        if isinstance(latest_service_dict.get("location_is_safe"), bool)
        else None,
        "is_mobile": latest_service_dict.get("is_mobile")
        if isinstance(latest_service_dict.get("is_mobile"), bool)
        else None,
        "complaint": _normalize_optional_str(latest_service_dict.get("service_complaint"))
        or _normalize_optional_str(session.get("service_complaint")),
    }

    has_first_name = customer["first_name"] is not None
    has_last_name = customer["last_name"] is not None
    has_phone = customer["phone"] is not None
    to_service_collection = has_first_name and has_last_name and has_phone

    has_location = service["location"] is not None
    has_complaint = service["complaint"] is not None
    has_vehicle_id = any((service["vin"], service["unit_number"], service["unit_nickname"]))
    has_saved_service = bool(services)
    to_booking = (
        to_service_collection
        and has_saved_service
        and has_location
        and has_complaint
        and has_vehicle_id
    )

    if not to_service_collection:
        current_phase = "customer_intake"
    elif not to_booking:
        current_phase = "service_collection"
    else:
        current_phase = "booking"

    missing_fields: list[str] = []
    if current_phase == "customer_intake":
        if not has_first_name:
            missing_fields.append("first_name")
        if not has_last_name:
            missing_fields.append("last_name")
        if not has_phone:
            missing_fields.append("phone")
    elif current_phase == "service_collection":
        if not has_location:
            missing_fields.append("location")
        if not has_complaint:
            missing_fields.append("complaint")
        if not has_vehicle_id:
            missing_fields.append("unit_number" if vin_fallback_triggered else "vin")
    else:
        services_confirmed = bool(session.get("services_confirmed", False))
        if not services_confirmed:
            missing_fields.append("confirmation")

    if current_phase == "customer_intake":
        if not has_first_name or not has_last_name:
            next_action = (
                "This is a new call. Start by collecting the customer's name."
                if is_session_empty
                else "Start by asking for the customer's name."
            )
        elif not has_phone:
            next_action = "Collect the customer's phone number"
        else:
            next_action = "Ready to hand off to ServiceCollection."
    elif current_phase == "service_collection":
        if not has_location and not has_complaint:
            next_action = "Ask what's wrong with the vehicle and where it's located."
        elif not has_complaint:
            next_action = "Ask what's wrong with the vehicle."
        elif not has_location:
            next_action = "Ask where the vehicle is located."
        elif not has_vehicle_id:
            next_action = (
                "VIN validation failed 3 times. Ask for the unit number or a nickname for the vehicle instead."
                if vin_fallback_triggered
                else "Ask for the vehicle's VIN"
            )
        elif not has_saved_service:
            next_action = (
                "Service details collected. Call add_service to save this service in the session."
            )
        else:
            next_action = "All information collected. Confirm details with customer and hand off to Booking."
    else:
        services_confirmed = bool(session.get("services_confirmed", False))
        next_action = (
            "All information collected. Confirm details with customer and hand off to Booking."
            if not services_confirmed
            else "Details confirmed. Proceed to store the service order."
        )

    booking_status = None
    if current_phase == "booking":
        booking_status = "confirmed" if bool(session.get("services_confirmed", False)) else "pending"

    booking = {
        "id": None,
        "eta": None,
        "technician": None,
        "status": booking_status,
    }

    case_state: dict[str, Any] = {
        "customer": customer,
        "service": service,
        "booking": booking,
        "missing_fields": missing_fields,
        "current_phase": current_phase,
        "ready_for_handoff": {
            "to_service_collection": to_service_collection,
            "to_booking": to_booking,
        },
        "next_action": next_action,
        "validation_state": {
            "phone_attempts": phone_attempts,
            "vin_attempts": vin_attempts,
            "vin_fallback_triggered": vin_fallback_triggered,
        },
    }

    if explicit_phase in {"completed", "correction"}:
        # Reason: Some flows set an explicit phase (e.g., after store_service_order).
        # get_case_status should respect that and avoid "resetting" back into intake.
        case_state["current_phase"] = explicit_phase
        case_state["missing_fields"] = []
        case_state["ready_for_handoff"] = {"to_service_collection": False, "to_booking": False}
        if isinstance(case_state.get("booking"), dict):
            case_state["booking"]["status"] = "completed" if explicit_phase == "completed" else case_state["booking"].get("status")

        case_state["next_action"] = (
            "Order completed. If the caller requests an update, collect the corrected value and call update_customer."
            if explicit_phase == "completed"
            else "Collect the corrected value and call update_customer, then return to completed."
        )

    return case_state
