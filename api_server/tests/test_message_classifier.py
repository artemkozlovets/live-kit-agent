import pytest


@pytest.mark.asyncio
async def test_frustrated_detection_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expected use: categorize common "are you there?" messages.

    We explicitly remove API keys so this test never makes a network call.
    """
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.vapi.message_classifier import MessageCategory, classify_message

    assert await classify_message("Hello?") == MessageCategory.FRUSTRATED
    assert await classify_message("Are you still there?") == MessageCategory.FRUSTRATED
    assert await classify_message("Hellooo?") == MessageCategory.FRUSTRATED
    assert await classify_message("Anyone listening?") == MessageCategory.FRUSTRATED


@pytest.mark.asyncio
async def test_blank_message_is_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge case: empty/near-empty inputs should be safe defaults."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.vapi.message_classifier import MessageCategory, classify_message

    assert await classify_message("") == MessageCategory.NORMAL
    assert await classify_message(" ") == MessageCategory.NORMAL
    assert await classify_message(".") == MessageCategory.NORMAL


def test_unknown_category_text_maps_to_normal() -> None:
    """Failure case: if the model returns junk, we default safely."""
    from api_server.vapi.message_classifier import MessageCategory, _category_from_text

    assert _category_from_text("WHATEVER") == MessageCategory.NORMAL
