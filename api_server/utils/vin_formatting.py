import re

VIN_NUMBER_REGEX = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


def normalize_vin_number(vin_number: str) -> str:
    return vin_number.strip().upper()


def is_vin_format_valid(vin_number: str) -> bool:
    normalized_vin_number = normalize_vin_number(vin_number)
    return bool(VIN_NUMBER_REGEX.fullmatch(normalized_vin_number))

