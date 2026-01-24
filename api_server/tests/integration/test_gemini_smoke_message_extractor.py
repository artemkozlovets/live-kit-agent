import os
import re

import pytest


def _has_gemini_api_key() -> bool:
    return any(
        (
            os.environ.get("GOOGLE_API_KEY", "").strip(),
            os.environ.get("GEMINI_API_KEY", "").strip(),
            os.environ.get("GEMINI_GUARD_API_KEY", "").strip(),
        )
    )


def _looks_like_phone(value: object) -> bool:
    if not isinstance(value, str):
        return False
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 10


@pytest.mark.asyncio
async def test_gemini_extract_customer_service_info_smoke() -> None:
    """Real network smoke test (skips unless an API key is configured)."""
    if not _has_gemini_api_key():
        pytest.skip("Requires GOOGLE_API_KEY/GEMINI_API_KEY/GEMINI_GUARD_API_KEY to call Gemini.")

    from api_server.vapi.message_extractor import extract_customer_service_info

    result = await extract_customer_service_info(
        "Hi, my name is John Johnson. My phone is 555-123-4567. I'm at 6th Street in Austin with a flat tire."
    )

    assert isinstance(result, dict)
    assert set(result.keys()) == {"customer", "service"}
    assert isinstance(result["customer"], dict)
    assert isinstance(result["service"], dict)

    # Reason: Model outputs can vary; keep smoke assertions flexible but meaningful.
    customer = result["customer"]
    service = result["service"]
    assert any(
        (
            isinstance(customer.get("first_name"), str) and customer.get("first_name"),
            isinstance(customer.get("last_name"), str) and customer.get("last_name"),
            _looks_like_phone(customer.get("phone")),
            isinstance(service.get("location"), str) and service.get("location"),
            isinstance(service.get("complaint"), str) and service.get("complaint"),
        )
    )

