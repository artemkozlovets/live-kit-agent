"""Gemini-backed message extraction for `get_case_status`.

This module extracts structured customer/service info from a raw `last_user_message`.

Design goals:
- No hard dependency on API keys (safe fallback to None).
- Best-effort parsing (never break call flow on extraction errors).
- Return only fields explicitly stated by the caller.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from api_server.vapi.message_classifier import _generate_gemini_text, _get_gemini_api_key

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """Extract customer and service info from this message. Return ONLY what is explicitly stated, null for anything not mentioned.

Fields:
- customer: first_name, last_name, phone, company
- service: location, complaint, unit_number, vin, vehicle_description

Return valid JSON only:
{"customer": {"first_name": null, "last_name": null, "phone": null, "company": null}, "service": {"location": null, "complaint": null, "unit_number": null, "vin": null, "vehicle_description": null}}

Message:
"""


def _get_extractor_model_name() -> str:
    model = os.environ.get("GEMINI_MESSAGE_EXTRACTOR_MODEL") or os.environ.get("GEMINI_CLASSIFIER_MODEL") or "gemini-2.5-flash"
    return model.strip() or "gemini-2.5-flash"


def _get_extractor_max_output_tokens() -> int:
    raw = os.environ.get("GEMINI_MESSAGE_EXTRACTOR_MAX_OUTPUT_TOKENS")
    if raw is None:
        # Reason: Gemini 2.5 models may consume a large "thoughts" budget; low token limits
        # can truncate JSON mid-object, causing parse failures in production.
        return 900
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return 900
    return parsed if parsed > 50 else 900


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.lstrip("`")
        newline = stripped.find("\n")
        stripped = stripped[newline + 1 :] if newline != -1 else stripped
        stripped = stripped.strip().rstrip("`").strip()
    return stripped


def _parse_json_object(text: str) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None

    stripped = _strip_code_fences(text)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # Best-effort: extract the first {...} block.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(stripped[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _clean_extracted_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    customer = payload.get("customer")
    service = payload.get("service")
    if not isinstance(customer, dict) or not isinstance(service, dict):
        return None

    clean_customer = {
        "first_name": _normalize_optional_str(customer.get("first_name")),
        "last_name": _normalize_optional_str(customer.get("last_name")),
        "phone": _normalize_optional_str(customer.get("phone")),
        "company": _normalize_optional_str(customer.get("company")),
    }
    clean_service = {
        "location": _normalize_optional_str(service.get("location")),
        "complaint": _normalize_optional_str(service.get("complaint")),
        "unit_number": _normalize_optional_str(service.get("unit_number")),
        "vin": _normalize_optional_str(service.get("vin")),
        "vehicle_description": _normalize_optional_str(service.get("vehicle_description")),
    }
    return {"customer": clean_customer, "service": clean_service}


async def extract_customer_service_info(last_user_message: str) -> dict[str, Any] | None:
    """Extract customer/service fields from a user message (best-effort)."""
    if not isinstance(last_user_message, str) or len(last_user_message.strip()) < 2:
        return None

    api_key = _get_gemini_api_key()
    if api_key is None:
        logger.warning("Gemini extraction skipped: missing API key")
        return None

    model = _get_extractor_model_name()
    logger.info("Gemini extraction start (model=%s, message_length=%s)", model, len(last_user_message))
    response_text = await _generate_gemini_text(
        prompt=f"{EXTRACTION_PROMPT}\n{last_user_message}",
        api_key=api_key,
        model=model,
        max_output_tokens=_get_extractor_max_output_tokens(),
        response_mime_type="application/json",
    )
    if response_text is None:
        logger.warning("Gemini extraction returned no text")
        return None

    parsed = _parse_json_object(response_text)
    if parsed is None:
        logger.warning("Gemini extraction returned invalid JSON")
        return None

    return _clean_extracted_payload(parsed)
