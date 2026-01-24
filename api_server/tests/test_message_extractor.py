import logging

import pytest


@pytest.mark.asyncio
async def test_extract_customer_service_info_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expected use: return cleaned fields when Gemini returns valid JSON."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    from api_server.vapi import message_extractor

    async def fake_generate(  # noqa: ANN001
        *,
        prompt: str,
        api_key: str,
        model: str,
        max_output_tokens: int,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        assert "Message:" in prompt
        assert api_key == "test-key"
        assert response_mime_type == "application/json"
        assert response_schema is None
        return (
            '{'
            '"customer": {"first_name": "John", "last_name": "Doe", "phone": "555-1234", "company": "Acme"},'
            '"service": {"location": "6th Street", "complaint": "Flat tire", "unit_number": "Unit 7",'
            '"vin": "VIN123", "vehicle_description": "Blue truck"}'
            '}'
        )

    monkeypatch.setattr(message_extractor, "_generate_gemini_text", fake_generate)

    result = await message_extractor.extract_customer_service_info("My name is John Doe and I'm at 6th Street.")

    assert result == {
        "customer": {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "555-1234",
            "company": "Acme",
        },
        "service": {
            "location": "6th Street",
            "complaint": "Flat tire",
            "unit_number": "Unit 7",
            "vin": "VIN123",
            "vehicle_description": "Blue truck",
        },
    }


@pytest.mark.asyncio
async def test_extract_customer_service_info_blank_message_returns_none() -> None:
    """Edge case: blank messages should be ignored without calling Gemini."""
    from api_server.vapi import message_extractor

    assert await message_extractor.extract_customer_service_info(" ") is None


@pytest.mark.asyncio
async def test_extract_customer_service_info_missing_key_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Failure case: missing API key should log and return None."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GUARD_API_KEY", raising=False)

    from api_server.vapi import message_extractor

    caplog.set_level(logging.WARNING, logger=message_extractor.__name__)
    result = await message_extractor.extract_customer_service_info("My last name is Johnson.")

    assert result is None
    assert "missing API key" in caplog.text


@pytest.mark.asyncio
async def test_extract_customer_service_info_invalid_json_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Failure case: invalid JSON from Gemini should log and return None."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    from api_server.vapi import message_extractor

    async def fake_generate(  # noqa: ANN001
        *,
        prompt: str,
        api_key: str,
        model: str,
        max_output_tokens: int,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        assert api_key == "test-key"
        assert response_mime_type == "application/json"
        assert response_schema is None
        return "sure! here's the json:\n{not actually valid json}\n"

    monkeypatch.setattr(message_extractor, "_generate_gemini_text", fake_generate)

    caplog.set_level(logging.WARNING, logger=message_extractor.__name__)
    result = await message_extractor.extract_customer_service_info("My last name is Johnson.")

    assert result is None
    assert "invalid JSON" in caplog.text
