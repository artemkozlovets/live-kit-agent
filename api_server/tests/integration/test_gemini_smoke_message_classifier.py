import os

import pytest


def _has_gemini_api_key() -> bool:
    return any(
        (
            os.environ.get("GOOGLE_API_KEY", "").strip(),
            os.environ.get("GEMINI_API_KEY", "").strip(),
            os.environ.get("GEMINI_GUARD_API_KEY", "").strip(),
        )
    )


@pytest.mark.asyncio
async def test_gemini_classify_message_smoke() -> None:
    """Real network smoke test (skips unless an API key is configured)."""
    if not _has_gemini_api_key():
        pytest.skip("Requires GOOGLE_API_KEY/GEMINI_API_KEY/GEMINI_GUARD_API_KEY to call Gemini.")

    from api_server.vapi.message_classifier import MessageCategory, classify_message

    category = await classify_message("Hello?")
    assert category == MessageCategory.FRUSTRATED
