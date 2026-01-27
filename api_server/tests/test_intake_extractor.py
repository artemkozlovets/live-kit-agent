from api_server.vapi.intake_extractor import extract_intake_info_fast


def test_extract_intake_info_fast_parses_spoken_digit_phone_and_email() -> None:
    result = extract_intake_info_fast(
        "My name is John Johnson. My phone number is three zero five three one seven nine eight four zero. "
        "My email is john@example.com."
    )

    assert result == {
        "customer": {
            "first_name": "John",
            "last_name": "Johnson",
            "phone": "3053179840",
            "company": None,
            "email_address": "john@example.com",
            "streetAddress": None,
            "city": None,
            "state": None,
            "postalCode": None,
            "customer_position": None,
            "marketing_source": None,
        },
        "service": {
            "location": None,
            "complaint": None,
            "unit_number": None,
            "vin": None,
            "vehicle_description": None,
        },
    }


def test_extract_intake_info_fast_blank_message_returns_none() -> None:
    assert extract_intake_info_fast(" ") is None


def test_extract_intake_info_fast_no_matches_returns_none() -> None:
    assert extract_intake_info_fast("Okay thanks.") is None

