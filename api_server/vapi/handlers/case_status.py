"""Case status Vapi tool handler (I/O + adapter layer)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from api_server.models.database_records import CustomerRecord
from api_server.models.inbound_models import InboundArgs
from api_server.server.dependencies import DatabaseClient
from api_server.vapi.correction_extractor import extract_corrections
from api_server.vapi.case_status import build_case_status
from api_server.vapi.fast_message_extractor import extract_customer_service_info_fast
from api_server.vapi.intake_extractor import extract_intake_info_fast
from api_server.vapi.message_extractor import extract_customer_service_info
from api_server.vapi.message_classifier import MessageCategory, classify_message, classify_message_heuristic
from api_server.vapi.response_mode import compute_response_mode
from api_server.vapi.session_store import SessionStore
from api_server.vapi.tool_call_parsing import get_call_id, parse_tool_arguments
from api_server.vapi.update_intents import detect_customer_update_intent
from api_server.utils.phone_formatting import normalize_us_phone_number


logger = logging.getLogger(__name__)

_NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{1,40}$")
_NAME_TOKEN_STOPWORDS: frozenset[str] = frozenset(
    {
        # Reason: Avoid treating common non-name tokens as names when callers answer prompts.
        "hello",
        "hi",
        "hey",
        "here",
        "yes",
        "no",
        "yep",
        "yeah",
        "nope",
        "ok",
        "okay",
        "thanks",
        "thank",
    }
)

_EXPECTED_FIELD_CUSTOMER: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "phone_number",
        "company_name",
        "email_address",
        "streetAddress",
        "city",
        "state",
        "postalCode",
    }
)
_EXPECTED_FIELD_SERVICE: frozenset[str] = frozenset(
    {
        "vin",
        "unit_number",
        "unit_nickname",
        "vehicle_identifier",
        "location",
        "complaint",
    }
)


def _normalize_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _get_override_customer_id(variable_values: dict[str, Any]) -> str | None:
    for key in ("customerId", "customer_id", "id"):
        customer_id = _normalize_optional_str(variable_values.get(key))
        if customer_id is not None:
            return customer_id
    return None


def _set_if_missing(session: dict[str, Any], key: str, value: str | None) -> None:
    if value is None:
        return
    existing = session.get(key)
    if isinstance(existing, str) and existing.strip():
        return
    session[key] = value


def _set_or_override(session: dict[str, Any], key: str, value: str | None, *, overwrite: bool) -> None:
    if value is None:
        return
    if overwrite:
        session[key] = value
        return
    _set_if_missing(session, key, value)


def _normalize_expected_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized in _EXPECTED_FIELD_CUSTOMER or normalized in _EXPECTED_FIELD_SERVICE:
        return normalized
    return None


def _apply_expected_field_answer(
    *,
    session: dict[str, Any],
    expected_field: str,
    answer: str,
) -> bool:
    if expected_field in _EXPECTED_FIELD_CUSTOMER:
        value = _normalize_optional_str(answer)
        if value is None:
            return False

        if expected_field == "first_name":
            session["first_name"] = value
            return True
        if expected_field == "last_name":
            session["last_name"] = value
            return True
        if expected_field == "phone_number":
            session["phone_number"] = value
            return True
        if expected_field == "company_name":
            session["company_name"] = value
            return True
        if expected_field == "email_address":
            session["email_address"] = value
            return True
        if expected_field == "streetAddress":
            session["streetAddress"] = value
            return True
        if expected_field == "city":
            session["city"] = value
            return True
        if expected_field == "state":
            session["state"] = value.upper() if len(value) == 2 else value
            return True
        if expected_field == "postalCode":
            session["postalCode"] = value
            return True

        return False

    if expected_field in _EXPECTED_FIELD_SERVICE:
        services = session.get("services", [])
        latest_service: dict[str, Any] | None = None
        if isinstance(services, list) and services and isinstance(services[-1], dict):
            latest_service = services[-1]

        service_target = latest_service if latest_service is not None else session
        value = _normalize_optional_str(answer)
        if value is None:
            return False

        if expected_field == "location":
            service_target["service_location"] = value
        elif expected_field == "complaint":
            service_target["service_complaint"] = value
        elif expected_field == "vin":
            service_target["vin_number"] = value
        elif expected_field == "unit_number":
            service_target["unit_number"] = value
        elif expected_field in {"unit_nickname", "vehicle_identifier"}:
            service_target["unit_nickname"] = value
        else:
            return False

        if latest_service is not None and isinstance(services, list):
            services[-1] = latest_service
            session["services"] = services
        return True

    return False


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None]:
    if not isinstance(full_name, str):
        return None, None
    parts = full_name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _extract_name_token(message: str) -> str | None:
    """Best-effort name capture from a 1-word reply (e.g., 'John')."""
    if not isinstance(message, str):
        return None

    stripped = message.strip()
    if not stripped:
        return None

    # Strip common punctuation at the edges (STT often includes trailing "." / "?").
    cleaned = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", stripped)
    if not cleaned:
        return None

    if not _NAME_TOKEN_RE.match(cleaned):
        return None

    if cleaned.lower() in _NAME_TOKEN_STOPWORDS:
        return None

    return cleaned.title()


def _extract_variable_values(message_payload: dict[str, Any]) -> dict[str, Any]:
    call_payload = message_payload.get("call")
    if isinstance(call_payload, dict):
        for override_key in ("assistantOverrides", "squadOverrides"):
            overrides = call_payload.get(override_key)
            if isinstance(overrides, dict):
                variable_values = overrides.get("variableValues")
                if isinstance(variable_values, dict):
                    return variable_values

    overrides = message_payload.get("assistantOverrides")
    if isinstance(overrides, dict):
        variable_values = overrides.get("variableValues")
        if isinstance(variable_values, dict):
            return variable_values

    overrides = message_payload.get("squadOverrides")
    if isinstance(overrides, dict):
        variable_values = overrides.get("variableValues")
        if isinstance(variable_values, dict):
            return variable_values

    return {}


def _get_caller_phone_number(message_payload: dict[str, Any]) -> str | None:
    call_payload = message_payload.get("call")
    if isinstance(call_payload, dict):
        call_customer = call_payload.get("customer")
        if isinstance(call_customer, dict):
            number = call_customer.get("number")
            if isinstance(number, str) and number.strip():
                return number.strip()
    return None


def _lookup_customer_by_phone(
    caller_phone: str,
    database_client: DatabaseClient,
) -> CustomerRecord | None:
    normalized_phone = normalize_us_phone_number(caller_phone)
    phone_for_lookup = normalized_phone or caller_phone
    inbound_args = InboundArgs(phone_number=phone_for_lookup)
    return database_client.find_customer_by_phone_number(inbound_args)


def _build_customer_record_from_overrides(
    variable_values: dict[str, Any],
) -> CustomerRecord | None:
    customer_id = _normalize_optional_str(variable_values.get("customerId"))
    if customer_id is None:
        return None

    customer_name = _normalize_optional_str(variable_values.get("customerName")) or ""
    customer_phone = _normalize_optional_str(variable_values.get("customerPhone")) or ""
    company_name = _normalize_optional_str(variable_values.get("companyName"))

    return CustomerRecord(
        customer_id=customer_id,
        customer_name=customer_name,
        phone_number=customer_phone,
        email=None,
        company_name=company_name,
    )


def _apply_known_customer_overrides(
    session: dict[str, Any],
    variable_values: dict[str, Any],
) -> None:
    customer_id = _normalize_optional_str(variable_values.get("customerId"))
    if customer_id is not None:
        session["customer_id"] = customer_id
        session["customer_registered"] = True

    customer_name = _normalize_optional_str(variable_values.get("customerName"))
    first_name, last_name = _split_full_name(customer_name)
    _set_if_missing(session, "first_name", first_name)
    _set_if_missing(session, "last_name", last_name)
    _set_if_missing(session, "phone_number", _normalize_optional_str(variable_values.get("customerPhone")))
    _set_if_missing(session, "company_name", _normalize_optional_str(variable_values.get("companyName")))


def _apply_known_customer_overrides_with_id(
    session: dict[str, Any],
    variable_values: dict[str, Any],
    customer_id: str,
) -> None:
    # Reason: Treat overrides-provided customerId as verified, regardless of isKnownCustomer.
    session["customer_id"] = customer_id
    session["customer_registered"] = True

    customer_name = _normalize_optional_str(variable_values.get("customerName"))
    first_name, last_name = _split_full_name(customer_name)
    _set_if_missing(session, "first_name", first_name)
    _set_if_missing(session, "last_name", last_name)
    _set_if_missing(session, "phone_number", _normalize_optional_str(variable_values.get("customerPhone")))
    _set_if_missing(session, "company_name", _normalize_optional_str(variable_values.get("companyName")))


def _build_customer_record_from_overrides_with_id(
    variable_values: dict[str, Any],
    customer_id: str,
) -> CustomerRecord:
    customer_name = _normalize_optional_str(variable_values.get("customerName")) or ""
    customer_phone = _normalize_optional_str(variable_values.get("customerPhone")) or ""
    company_name = _normalize_optional_str(variable_values.get("companyName"))

    return CustomerRecord(
        customer_id=customer_id,
        customer_name=customer_name,
        phone_number=customer_phone,
        email=None,
        company_name=company_name,
    )


def _build_service_collection_prompt(
    *,
    has_vehicle_id: bool,
    has_location: bool,
    has_complaint: bool,
) -> tuple[str, str]:
    if not has_vehicle_id:
        return (
            "Ask for the vehicle's VIN, unit number, or nickname.",
            "What vehicle do you need service for?",
        )
    if not has_location:
        return (
            "Ask where the vehicle is located.",
            "Where is the vehicle located?",
        )
    if not has_complaint:
        return (
            "Ask what's wrong with the vehicle.",
            "What's the issue with the vehicle?",
        )
    return (
        "All service details collected. Handoff to Booking.",
        "Thanks! I have everything I need to get you booked.",
    )


def _apply_customer_record_to_session(
    session: dict[str, Any],
    customer_record: CustomerRecord,
) -> None:
    session["customer_id"] = customer_record.customer_id
    session["customer_registered"] = True
    first_name, last_name = _split_full_name(customer_record.customer_name)
    _set_if_missing(session, "first_name", first_name)
    _set_if_missing(session, "last_name", last_name)
    _set_if_missing(session, "phone_number", _normalize_optional_str(customer_record.phone_number))
    _set_if_missing(session, "company_name", _normalize_optional_str(customer_record.company_name))


def _build_phone_confirmation_message(
    customer_record: CustomerRecord | None,
    caller_phone: str | None,
) -> str:
    first_name, _ = _split_full_name(customer_record.customer_name if customer_record else None)
    name = first_name or "there"
    phone = caller_phone or (customer_record.phone_number if customer_record else None)
    if phone:
        return (
            f"Hey {name}! I've got your number as {phone} - "
            "is this still the best number to reach you?"
        )
    return f"Hey {name}! Is this still the best number to reach you?"


def _build_customer_known_data(session: dict[str, Any]) -> dict[str, Any]:
    # Reason: The slot-filling agent needs a stable, structured view of the session
    # so it can make deterministic tool calls (register/add_service/store order)
    # without requiring an LLM to reconstruct arguments.
    return {
        "first_name": _normalize_optional_str(session.get("first_name")),
        "last_name": _normalize_optional_str(session.get("last_name")),
        "company_name": _normalize_optional_str(session.get("company_name")),
        "email_address": _normalize_optional_str(session.get("email_address")),
        "phone_number": _normalize_optional_str(session.get("phone_number") or session.get("phone")),
        "customer_position": _normalize_optional_str(session.get("customer_position")),
        "marketing_source": _normalize_optional_str(session.get("marketing_source")),
        "streetAddress": _normalize_optional_str(session.get("streetAddress")),
        "city": _normalize_optional_str(session.get("city")),
        "state": _normalize_optional_str(session.get("state")),
        "country": _normalize_optional_str(session.get("country")),
        "postalCode": _normalize_optional_str(session.get("postalCode")),
    }


async def handle_get_case_status(
    tool_call: dict[str, Any],
    message_payload: dict[str, Any],
    session_store: SessionStore,
    database_client: DatabaseClient,
) -> dict[str, Any]:
    tool_arguments = parse_tool_arguments(tool_call)
    # Reason: Vapi tool arguments may contain unresolved placeholders; prefer payload call ID.
    call_id = get_call_id(message_payload)

    last_user_message = tool_arguments.get("last_user_message")
    last_user_message = (
        last_user_message.strip()
        if isinstance(last_user_message, str) and last_user_message.strip()
        else None
    )
    handoff_initiated = False
    if isinstance(last_user_message, str):
        normalized_message = last_user_message.strip().lower()
        if normalized_message in {"handoff initiated.", "handoff initiated"}:
            handoff_initiated = True
            last_user_message = None

    expected_field = _normalize_expected_field(tool_arguments.get("expected_field"))

    variable_values = _extract_variable_values(message_payload)
    override_customer_id = _get_override_customer_id(variable_values)
    if override_customer_id is not None:
        session = session_store.get(call_id) if call_id else {}
        if call_id:
            _apply_known_customer_overrides_with_id(session, variable_values, override_customer_id)
            session_store.set(call_id, session)

        customer_record = _build_customer_record_from_overrides_with_id(
            variable_values,
            override_customer_id,
        )
        case_status = build_case_status(session=session, customer_record=customer_record)
        service = case_status.get("service") if isinstance(case_status.get("service"), dict) else {}

        has_vehicle_id = any(
            _normalize_optional_str(service.get(key)) is not None
            for key in ("vin", "unit_number", "unit_nickname")
        )
        has_location = _normalize_optional_str(service.get("location")) is not None
        has_complaint = _normalize_optional_str(service.get("complaint")) is not None

        missing_fields = []
        if not has_vehicle_id:
            missing_fields.append("vehicle_identifier")
        if not has_location:
            missing_fields.append("location")
        if not has_complaint:
            missing_fields.append("complaint")

        next_action, immediate_message = _build_service_collection_prompt(
            has_vehicle_id=has_vehicle_id,
            has_location=has_location,
            has_complaint=has_complaint,
        )

        case_status.update(
            {
                "missing_fields": missing_fields,
                "current_phase": "service_collection",
                "ready_for_handoff": {
                    "to_service_collection": True,
                    "to_booking": not missing_fields,
                },
                "next_action": next_action,
                "response_mode": "speak_first",
                "immediate_message": immediate_message,
                "then_action": "collect_service_info",
            }
        )
        return case_status

    # Performance note:
    # `get_case_status` runs on every turn, so any network calls here (Gemini, DB)
    # can cause multi-second tool latency and trigger filler speech in Vapi.
    tools_api_version = message_payload.get("_tools_api_version")
    is_tools_v2 = tools_api_version == 2

    if is_tools_v2:
        # Reason: /tools is the OpenAI Realtime cutover path and must never require
        # Gemini keys or incur Gemini latency, regardless of env flags.
        use_gemini_classification = False
        use_gemini_extraction = False
        use_gemini_corrections = False
        # Reason: Keep slot-filling deterministic for the agent by default (no network).
        use_fast_extractor = True
        slot_filling = True
    else:
        use_gemini_classification = _env_flag("GET_CASE_STATUS_GEMINI_CLASSIFICATION", True)
        use_gemini_extraction = _env_flag("GET_CASE_STATUS_GEMINI_EXTRACTION", True)
        use_gemini_corrections = _env_flag("GET_CASE_STATUS_GEMINI_CORRECTIONS", True)
        use_fast_extractor = _env_flag("GET_CASE_STATUS_FAST_EXTRACTOR", False)
        slot_filling = _env_flag("GET_CASE_STATUS_SLOT_FILLING", False)

    category = MessageCategory.NORMAL
    if last_user_message is not None:
        category = (
            await classify_message(last_user_message)
            if use_gemini_classification
            else classify_message_heuristic(last_user_message)
        )

    session = session_store.get(call_id) if call_id else {}
    if slot_filling and call_id and expected_field is not None and isinstance(last_user_message, str):
        try:
            if _apply_expected_field_answer(
                session=session,
                expected_field=expected_field,
                answer=last_user_message,
            ):
                session_store.set(call_id, session)
        except Exception:
            logger.exception(
                "get_case_status expected_field handling failed",
                extra={"call_id": call_id, "expected_field": expected_field},
            )
    customer_record = None
    customer_source = None

    is_known_customer = (
        variable_values.get("isKnownCustomer", "")
        if isinstance(variable_values, dict)
        else ""
    )
    if isinstance(is_known_customer, str) and is_known_customer.strip().lower() == "true":
        customer_record = _build_customer_record_from_overrides(variable_values)
        if customer_record is not None:
            customer_source = "overrides"
        if customer_record is not None and call_id:
            _apply_known_customer_overrides(session, variable_values)
            session_store.set(call_id, session)

    if customer_record is None:
        customer_id = session.get("customer_id")
        if isinstance(customer_id, str) and customer_id:
            try:
                customer_record = database_client.find_customer_by_id(customer_id)
                if customer_record is not None:
                    customer_source = "session"
            except NotImplementedError:
                # Reason: get_case_status can still guide the call without DB access.
                customer_record = None

    caller_phone = None
    if customer_record is None:
        caller_phone = _get_caller_phone_number(message_payload)
        if caller_phone:
            try:
                customer_record = _lookup_customer_by_phone(caller_phone, database_client)
                if customer_record is not None:
                    customer_source = "caller_phone"
                    if call_id:
                        _apply_customer_record_to_session(session, customer_record)
                        if handoff_initiated:
                            session["phone_confirmed"] = True
                            session.pop("phone_confirmation_pending", None)
                        elif not session.get("phone_confirmed") and not session.get(
                            "phone_confirmation_pending"
                        ):
                            session["phone_confirmation_pending"] = True
                        session_store.set(call_id, session)
            except Exception:
                # Reason: DB lookup should never break the call flow.
                logger.exception("get_case_status caller phone lookup failed", extra={"call_id": call_id})

    if last_user_message is not None and call_id:
        try:
            extracted_payloads: list[tuple[str, dict[str, Any]]] = []

            extracted: dict[str, Any] | None = None
            if use_gemini_extraction:
                extracted = await extract_customer_service_info(last_user_message)
                # Reason: Gemini can fail (invalid JSON / timeouts). When enabled, allow a
                # deterministic fallback so the conversation can still progress.
                if extracted is None and use_fast_extractor:
                    extracted = extract_customer_service_info_fast(last_user_message)
            elif use_fast_extractor:
                extracted = extract_customer_service_info_fast(last_user_message)

            if isinstance(extracted, dict):
                extracted_payloads.append(("default", extracted))

            if slot_filling:
                slot_extracted = extract_intake_info_fast(last_user_message)
                if isinstance(slot_extracted, dict):
                    extracted_payloads.append(("slot", slot_extracted))

            for source, payload in extracted_payloads:
                overwrite = source == "slot"
                extracted_customer = payload.get("customer")
                extracted_service = payload.get("service")

                if isinstance(extracted_customer, dict):
                    _set_or_override(
                        session,
                        "first_name",
                        _normalize_optional_str(extracted_customer.get("first_name")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        session,
                        "last_name",
                        _normalize_optional_str(extracted_customer.get("last_name")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        session,
                        "phone_number",
                        _normalize_optional_str(extracted_customer.get("phone")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        session,
                        "company_name",
                        _normalize_optional_str(extracted_customer.get("company")),
                        overwrite=overwrite,
                    )

                    if slot_filling:
                        _set_or_override(
                            session,
                            "email_address",
                            _normalize_optional_str(extracted_customer.get("email_address")),
                            overwrite=overwrite,
                        )
                        _set_or_override(
                            session,
                            "streetAddress",
                            _normalize_optional_str(extracted_customer.get("streetAddress")),
                            overwrite=overwrite,
                        )
                        _set_or_override(
                            session,
                            "city",
                            _normalize_optional_str(extracted_customer.get("city")),
                            overwrite=overwrite,
                        )
                        state = _normalize_optional_str(extracted_customer.get("state"))
                        _set_or_override(
                            session,
                            "state",
                            state.upper() if state is not None else None,
                            overwrite=overwrite,
                        )
                        _set_or_override(
                            session,
                            "postalCode",
                            _normalize_optional_str(extracted_customer.get("postalCode")),
                            overwrite=overwrite,
                        )
                        _set_or_override(
                            session,
                            "customer_position",
                            _normalize_optional_str(extracted_customer.get("customer_position")),
                            overwrite=overwrite,
                        )
                        _set_or_override(
                            session,
                            "marketing_source",
                            _normalize_optional_str(extracted_customer.get("marketing_source")),
                            overwrite=overwrite,
                        )

                    updates_for_db: dict[str, object] = {}
                    if customer_record is not None and use_gemini_extraction:
                        extracted_company = _normalize_optional_str(extracted_customer.get("company"))
                        if extracted_company is not None:
                            stored_company = _normalize_optional_str(customer_record.company_name)
                            if stored_company is None:
                                updates_for_db["company_name"] = extracted_company

                        stored_contact_name = _normalize_optional_str(customer_record.customer_name)
                        if stored_contact_name is None:
                            extracted_first = _normalize_optional_str(extracted_customer.get("first_name"))
                            extracted_last = _normalize_optional_str(extracted_customer.get("last_name"))
                            if extracted_first is not None or extracted_last is not None:
                                updates_for_db["contact_name"] = " ".join(
                                    part for part in (extracted_first, extracted_last) if part
                                )

                        stored_phone = _normalize_optional_str(customer_record.phone_number)
                        if stored_phone is None:
                            extracted_phone = _normalize_optional_str(extracted_customer.get("phone"))
                            if extracted_phone is not None:
                                updates_for_db["phone_number"] = extracted_phone

                    update_customer = getattr(database_client, "update_customer", None)
                    if (
                        customer_record is not None
                        and updates_for_db
                        and callable(update_customer)
                    ):
                        try:
                            update_customer(customer_record.customer_id, updates_for_db)
                        except NotImplementedError:
                            # Reason: DB writes are optional; keep session-based extraction.
                            pass

                if isinstance(extracted_service, dict):
                    services = session.get("services", [])
                    latest_service: dict[str, Any] | None = None
                    if isinstance(services, list) and services and isinstance(services[-1], dict):
                        latest_service = services[-1]

                    # Reason: Prefer saving service fields into the current service (if one exists),
                    # otherwise store them on session for case-status completeness checks.
                    service_target = latest_service if latest_service is not None else session
                    _set_or_override(
                        service_target,
                        "service_location",
                        _normalize_optional_str(extracted_service.get("location")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        service_target,
                        "service_complaint",
                        _normalize_optional_str(extracted_service.get("complaint")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        service_target,
                        "unit_number",
                        _normalize_optional_str(extracted_service.get("unit_number")),
                        overwrite=overwrite,
                    )
                    _set_or_override(
                        service_target,
                        "vin_number",
                        _normalize_optional_str(extracted_service.get("vin")),
                        overwrite=overwrite,
                    )
                    vehicle_description = _normalize_optional_str(extracted_service.get("vehicle_description"))
                    _set_or_override(
                        service_target,
                        "vehicle_description",
                        vehicle_description,
                        overwrite=overwrite,
                    )
                    # Reason: Some callers describe the vehicle (e.g. "blue truck") instead of
                    # providing a VIN/unit number. Treat it as a nickname so we can move on.
                    _set_or_override(
                        service_target,
                        "unit_nickname",
                        vehicle_description,
                        overwrite=overwrite,
                    )

                    if latest_service is not None and isinstance(services, list):
                        services[-1] = latest_service
                        session["services"] = services

            if extracted_payloads:
                session_store.set(call_id, session)
        except Exception:
            # Reason: Extraction is best-effort and should never break the call flow.
            logger.exception("get_case_status message extraction failed", extra={"call_id": call_id})

    case_status = build_case_status(session=session, customer_record=customer_record)

    if last_user_message is not None and call_id and category == MessageCategory.NORMAL:
        name_token = _extract_name_token(last_user_message)
        if (
            isinstance(name_token, str)
            and name_token
            and case_status.get("current_phase") == "customer_intake"
        ):
            missing_fields = (
                case_status.get("missing_fields")
                if isinstance(case_status.get("missing_fields"), list)
                else []
            )
            if "first_name" in missing_fields:
                before = session.get("first_name")
                _set_if_missing(session, "first_name", name_token)
                if session.get("first_name") != before:
                    session_store.set(call_id, session)
                    case_status = build_case_status(session=session, customer_record=customer_record)
            elif "last_name" in missing_fields and _normalize_optional_str(session.get("first_name")) is not None:
                before = session.get("last_name")
                _set_if_missing(session, "last_name", name_token)
                if session.get("last_name") != before:
                    session_store.set(call_id, session)
                    case_status = build_case_status(session=session, customer_record=customer_record)

    phone_confirmation_pending = bool(session.get("phone_confirmation_pending", False))
    if (
        phone_confirmation_pending
        and last_user_message is not None
        and category == MessageCategory.CONFIRMATION
        and call_id
    ):
        session["phone_confirmation_pending"] = False
        session["phone_confirmed"] = True
        session_store.set(call_id, session)
        phone_confirmation_pending = False
        case_status = build_case_status(session=session, customer_record=customer_record)
        case_status.update(
            {
                "message_category": category.value,
                "response_mode": "speak_first",
                "immediate_message": "Great! What can I help you with?",
                "then_action": "Collect service details.",
                "detected_corrections": None,
            }
        )
        return case_status

    if phone_confirmation_pending:
        case_status.update(
            {
                "current_phase": "customer_intake",
                "missing_fields": ["phone_confirmation"],
                "ready_for_handoff": {"to_service_collection": False, "to_booking": False},
                "next_action": "Confirm the caller's phone number, then hand off to ServiceCollection.",
            }
        )
        if last_user_message is None:
            return case_status

        case_status.update(
            {
                "message_category": category.value,
                "response_mode": "speak_first",
                "immediate_message": _build_phone_confirmation_message(
                    customer_record,
                    caller_phone,
                ),
                "then_action": "Ask the caller to confirm the phone number.",
                "detected_corrections": None,
            }
        )
        return case_status

    customer_payload = case_status.get("customer") if isinstance(case_status.get("customer"), dict) else {}
    missing_fields = case_status.get("missing_fields") if isinstance(case_status.get("missing_fields"), list) else []
    if (
        customer_payload.get("id") is not None
        and not missing_fields
        and isinstance(case_status.get("current_phase"), str)
        and case_status.get("current_phase") != "booking"
    ):
        case_status.update(
            {
                "current_phase": "service_collection",
                "ready_for_handoff": {"to_service_collection": True, "to_booking": False},
                "next_action": "Collect vehicle info and service complaint.",
            }
        )

    if slot_filling:
        case_status["customer_known_data"] = _build_customer_known_data(session)

    # Backwards-compat: only add message-aware fields when callers pass last_user_message.
    if last_user_message is None:
        if handoff_initiated and customer_record is not None:
            case_status.update(
                {
                    "current_phase": "service_collection",
                    "missing_fields": [],
                    "ready_for_handoff": {"to_service_collection": True, "to_booking": False},
                    "next_action": "Collect vehicle info and service complaint.",
                    "response_mode": "speak_first",
                    "immediate_message": "What can I help you with today?",
                    "then_action": "Collect vehicle info and service complaint.",
                    "detected_corrections": None,
                    "message_category": MessageCategory.NORMAL.value,
                }
            )
        return case_status

    update_intent = detect_customer_update_intent(last_user_message)
    customer = case_status.get("customer") if isinstance(case_status.get("customer"), dict) else {}
    customer_id_for_update = customer.get("id")
    if (
        update_intent is not None
        and isinstance(customer_id_for_update, str)
        and customer_id_for_update
        and call_id
    ):
        # Reason: Persist the pending correction so subsequent turns can stay in correction mode.
        session["current_phase"] = "correction"
        session["pending_correction"] = {"field": update_intent.field, "customer_id": customer_id_for_update}
        session_store.set(call_id, session)

        if update_intent.field == "streetAddress":
            then_action = (
                f"Collect the caller's full address, then call update_customer with customer_id={customer_id_for_update} "
                "and updates={streetAddress, city, state, postalCode}. Then return to completed."
            )
        else:
            then_action = (
                f"Collect the new {update_intent.friendly_field}, then call update_customer with customer_id={customer_id_for_update} "
                f"and updates={{{update_intent.field}: <new_value>}}. Then return to completed."
            )

        case_status.update(
            {
                "message_category": MessageCategory.CORRECTION.value,
                "current_phase": "correction",
                "response_mode": "speak_first",
                "immediate_message": f"Sure, what's your new {update_intent.friendly_field}?",
                "then_action": then_action,
                "detected_corrections": {
                    "field": update_intent.field,
                    "customer_id": customer_id_for_update,
                },
            }
        )
        return case_status

    response_mode, immediate_message, then_action_override = compute_response_mode(
        category=category,
        case_state=case_status,
        last_message=last_user_message,
    )
    then_action = case_status.get("next_action")
    if then_action_override is not None:
        # Reason: Allow empty-string overrides to suppress tool parsing when we only need a prompt.
        then_action = then_action_override

    detected_corrections = None
    if category == MessageCategory.CORRECTION and use_gemini_corrections:
        detected_corrections = await extract_corrections(last_user_message, case_status)

    case_status.update(
        {
            "message_category": category.value,
            "response_mode": response_mode,
            "immediate_message": immediate_message,
            "then_action": then_action,
            "detected_corrections": detected_corrections,
        }
    )
    return case_status
