"""Order-related Vapi tool handlers (persistence + side effects)."""

from __future__ import annotations

from typing import Any

from api_server.models.database_records import UnitAutoCreateResult
from api_server.models.store_service_order_models import StoreServiceOrderArgs
from api_server.server.dependencies import DatabaseClient
from api_server.utils.vin_formatting import normalize_vin_number
from api_server.vapi.unit_resolution import resolve_unit_or_create
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_call_id, parse_tool_arguments


def _resolve_unit_id_from_service(
    *,
    service: dict[str, Any],
    database_client: DatabaseClient,
    customer_id: str,
):
    unit_id = service.get("unit_id")
    if isinstance(unit_id, str) and unit_id:
        # Reason: If unit_id is already provided, skip lookup and auto-create.
        return UnitAutoCreateResult(unit_id=unit_id, was_created=False)

    raw_vin_number = service.get("vin_number")
    vin_number = None
    if isinstance(raw_vin_number, str) and raw_vin_number:
        # Reason: Normalize VINs to improve match rate (case/spacing).
        vin_number = normalize_vin_number(raw_vin_number)

    unit_number = service.get("unit_number")
    if not isinstance(unit_number, str):
        unit_number = None

    unit_nickname = service.get("unit_nickname")
    if not isinstance(unit_nickname, str):
        unit_nickname = None

    vehicle_make = service.get("vehicle_make")
    if not isinstance(vehicle_make, str):
        vehicle_make = None
    vehicle_model = service.get("vehicle_model")
    if not isinstance(vehicle_model, str):
        vehicle_model = None

    return resolve_unit_or_create(
        vin_number=vin_number,
        unit_number=unit_number,
        unit_nickname=unit_nickname,
        make=vehicle_make,
        model=vehicle_model,
        db_client=database_client,
        customer_id=customer_id,
        auto_create=True,
    )


def handle_store_service_order(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    _ = tool_call
    call_id = get_call_id(message_payload)

    session = session_store.get(call_id)
    services = session.get("services", [])
    if not isinstance(services, list) or not services:
        return {
            "success": False,
            "error": "No services to order",
            "next_action": "No services collected yet. Use add_service to collect service details first.",
        }

    customer_id = session.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        return {
            "success": False,
            "error": "Customer data required",
            "next_action": (
                "Customer not identified. Call handoff_to_CustomerIntake to "
                "collect customer details."
            ),
        }

    # Reason: Fail-fast before any writes or unit auto-creation.
    customer_exists = database_client.customer_exists(
        StoreServiceOrderArgs(customer_id=customer_id, unit_id="UNKNOWN")
    )
    if not customer_exists:
        return {"success": False, "error": "Customer not found"}

    store_service_order_args_list: list[StoreServiceOrderArgs] = []
    for service in services:
        if not isinstance(service, dict):
            return {"success": False, "error": "Invalid service data"}

        resolution = _resolve_unit_id_from_service(
            service=service,
            database_client=database_client,
            customer_id=customer_id,
        )
        if resolution.error:
            response = {"success": False, "error": resolution.error}
            if resolution.matching_units:
                response["matching_units"] = resolution.matching_units
            return response
        if resolution.unit_id is None:
            return {"success": False, "error": "Unit not found"}

        service_location = service.get("service_location")
        service_complaint = service.get("service_complaint")

        store_service_order_args_list.append(
            StoreServiceOrderArgs(
                customer_id=customer_id,
                unit_id=resolution.unit_id,
                service_location=service_location if isinstance(service_location, str) else None,
                service_complaint=service_complaint if isinstance(service_complaint, str) else None,
            )
        )

    for store_service_order_args in store_service_order_args_list:
        unit_record = database_client.find_unit_for_service_order(store_service_order_args)
        if unit_record is None:
            return {"success": False, "error": "Unit not found"}

        unit_belongs_to_customer = unit_record.customer_id == customer_id
        if not unit_belongs_to_customer:
            return {"success": False, "error": "Unit does not belong to customer"}

    order_ids: list[str] = []
    for store_service_order_args in store_service_order_args_list:
        service_order_id = database_client.create_service_order(store_service_order_args)
        order_ids.append(service_order_id)

    # Reason: Preserve call-scoped state for the rest of the call so callers can
    # request corrections ("update my phone number") without losing customer_id.
    session["current_phase"] = "completed"
    session["order_ids"] = order_ids
    session["customer_registered"] = True
    session_store.set(call_id, session)
    # Reason: Guide assistant to send confirmation and wrap up the call
    return {
        "success": True,
        "order_ids": order_ids,
        "next_action": "Order confirmed. Call send_confirmation_sms, then thank the caller and end the call.",
    }


def handle_update_service_order(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    tool_arguments = parse_tool_arguments(tool_call)
    order_id = tool_arguments.get("order_id")
    updates = tool_arguments.get("updates")
    updates_dict = updates if isinstance(updates, dict) else {}

    updated_fields = [
        field for field, value in updates_dict.items() if value is not None
    ]

    if isinstance(order_id, str) and order_id:
        order_record = database_client.find_service_order_by_id(order_id)
        if order_record is None:
            return {
                "success": False,
                "error": "Service order not found",
                "next_action": "Could not find that service order.",
            }

        updates_for_db = dict(updates_dict)

        has_vehicle_identifier = any(
            updates_dict.get(key) for key in ("vin_number", "unit_number", "unit_nickname")
        )
        if has_vehicle_identifier:
            # Reason: If vehicle identifiers changed, resolve to a concrete unit_id first.
            resolution = _resolve_unit_id_from_service(
                service=updates_dict,
                database_client=database_client,
                customer_id=order_record.customer_id,
            )
            if resolution.error:
                response: dict[str, Any] = {"success": False, "error": resolution.error}
                if resolution.matching_units:
                    response["matching_units"] = resolution.matching_units
                return response
            if resolution.unit_id is None:
                return {"success": False, "error": "Unit not found"}

            updates_for_db["unit_id"] = resolution.unit_id

        updated_order_id = database_client.update_service_order(order_id, updates_for_db)
        if updated_order_id is None:
            return {
                "success": False,
                "error": "Service order not found",
                "next_action": "Could not find that service order.",
            }

        return {
            "success": True,
            "updated_fields": updated_fields,
            "order_id": order_id,
            "next_action": "Service order updated. Continue with the call.",
        }

    call_id = get_call_id(message_payload)
    session = session_store.get(call_id)
    services = session.get("services", [])
    if not isinstance(services, list) or not services:
        return {
            "success": False,
            "error": "No services in session",
            "next_action": "No service has been added yet. Collect service details first.",
        }

    latest_service = services[-1]
    if not isinstance(latest_service, dict):
        return {
            "success": False,
            "error": "Invalid service data",
            "next_action": "No service has been added yet. Collect service details first.",
        }

    for field, value in updates_dict.items():
        if value is None:
            continue
        latest_service[field] = value

    services[-1] = latest_service
    session["services"] = services
    if call_id:
        session_store.set(call_id, session)

    return {
        "success": True,
        "updated_fields": updated_fields,
        "order_id": "session",
        "next_action": "Service order updated. Continue with the call.",
    }
