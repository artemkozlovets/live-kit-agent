from api_server.vapi.fast_message_extractor import extract_customer_service_info_fast


def test_extract_customer_service_info_fast_parses_explicit_fields() -> None:
    """Expected use: extract explicitly stated fields without network calls."""
    result = extract_customer_service_info_fast(
        "My name is John Johnson. My phone is 555-123-4567. I'm at 6th Street in Austin with a flat tire."
    )

    assert result == {
        "customer": {
            "first_name": "John",
            "last_name": "Johnson",
            "phone": "555-123-4567",
            "company": None,
        },
        "service": {
            "location": "6th Street in Austin with a flat tire",
            "complaint": "flat tire",
            "unit_number": None,
            "vin": None,
            "vehicle_description": None,
        },
    }


def test_extract_customer_service_info_fast_blank_message_returns_none() -> None:
    """Edge case: blank input should return None."""
    assert extract_customer_service_info_fast(" ") is None


def test_extract_customer_service_info_fast_no_matches_returns_none() -> None:
    """Failure case: return None when nothing looks explicitly stated."""
    assert extract_customer_service_info_fast("Okay thanks.") is None

