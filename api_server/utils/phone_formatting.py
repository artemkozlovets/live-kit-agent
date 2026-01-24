import re

PHONE_NUMBER_DIGITS_REGEX = re.compile(r"\d{10}")


def normalize_us_phone_number(phone_number: str) -> str | None:
    # Reason: Strip all non-digits so STT artifacts like spaces, dashes, or "?" don't break validation.
    digits_only = re.sub(r"\D", "", phone_number or "")

    # Reason: Some callers/models include the US country code more than once (e.g., "+11...").
    # Strip leading "1" until we have 10 digits (or the prefix stops being "1").
    while len(digits_only) > 10 and digits_only.startswith("1"):
        digits_only = digits_only[1:]

    is_phone_valid = bool(PHONE_NUMBER_DIGITS_REGEX.fullmatch(digits_only))
    if not is_phone_valid:
        return None

    return f"+1{digits_only}"
