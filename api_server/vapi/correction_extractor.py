"""Gemini-backed correction extraction (optional enhancement).

This is only used when callers pass `last_user_message` and it is classified as
CORRECTION. If Gemini is unavailable, we return None and let the normal flow
continue.
"""

from __future__ import annotations

import json
import os
from typing import Any

from api_server.vapi.message_classifier import _generate_gemini_text, _get_gemini_api_key


_JSON_SHAPE_EXAMPLE = """{
  "corrections": [
    {"field": "first_name", "old_value": "if known", "new_value": "Robert", "tool": "update_customer"}
  ]
}"""


def _get_extractor_model_name() -> str:
    # Reason: let us tune extraction separately from classification.
    model = os.environ.get("GEMINI_CORRECTION_EXTRACTOR_MODEL") or os.environ.get("GEMINI_CLASSIFIER_MODEL") or "gemini-2.5-flash"
    return model.strip() or "gemini-2.5-flash"

def _get_extractor_max_output_tokens() -> int:
    raw = os.environ.get("GEMINI_CORRECTION_EXTRACTOR_MAX_OUTPUT_TOKENS")
    if raw is None:
        # Reason: Same as message extraction: guard against truncated JSON when Gemini spends
        # a large hidden "thoughts" budget.
        return 600
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return 600
    return parsed if parsed > 50 else 600


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.lstrip("`")
        # Trim optional language label (e.g., "json")
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


async def extract_corrections(message: str, case_state: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extract specific field corrections from a user message."""
    api_key = _get_gemini_api_key()
    if api_key is None:
        return None

    customer_json = json.dumps(case_state.get("customer", {}), ensure_ascii=False)
    service_json = json.dumps(case_state.get("service", {}), ensure_ascii=False)
    prompt = f"""Extract corrections from this customer message.

Current data on file:
- Customer: {customer_json}
- Service: {service_json}

Customer message: "{message}"

If the customer is correcting any of this data, return JSON with this shape:
{_JSON_SHAPE_EXAMPLE}

Field mapping:
- Name corrections -> field: "first_name" or "last_name", tool: "update_customer"
- Phone corrections -> field: "phone_number", tool: "update_customer"
- Email corrections -> field: "email_address", tool: "update_customer"
- Location corrections -> field: "service_location", tool: "update_service_order"
- Vehicle corrections -> field: "vin_number", "unit_number", or "unit_nickname", tool: "update_service_order"
- Complaint corrections -> field: "service_complaint", tool: "update_service_order"

If no corrections found, return: {{"corrections": []}}

Return ONLY valid JSON, nothing else."""

    try:
        response_text = await _generate_gemini_text(
            prompt=prompt,
            api_key=api_key,
            model=_get_extractor_model_name(),
            max_output_tokens=_get_extractor_max_output_tokens(),
            response_mime_type="application/json",
        )
        if response_text is None:
            return None

        parsed = _parse_json_object(response_text)
        if parsed is None:
            return None

        corrections = parsed.get("corrections")
        if not isinstance(corrections, list):
            return None

        return [entry for entry in corrections if isinstance(entry, dict)]
    except Exception:
        # Reason: extraction is best-effort and should not break the call flow.
        return None
