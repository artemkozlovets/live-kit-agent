"""Tests for unique key generation utilities.

These utilities generate collision-resistant identifiers for:
- Customer codes (CUST-XXXXXXXX)
- Service order numbers (SO-YYYYMMDD-XXXXXX)
- Placeholder VINs (NO-VIN-xxxxxxxx)
"""

import re
from datetime import date

from api_server.utils.key_generation import (
    generate_customer_code,
    generate_placeholder_vin,
    generate_service_order_number,
)


# === Customer Code Tests ===


def test_generate_customer_code_has_correct_format() -> None:
    """Customer code must be CUST- followed by 8 alphanumeric chars.

    Format: CUST-XXXXXXXX where X is uppercase alphanumeric.
    Total length: 13 characters (5 prefix + 8 suffix).
    """
    # Arrange
    # (no setup needed for pure function)

    # Act
    code = generate_customer_code()

    # Assert
    assert code.startswith("CUST-"), f"Code should start with 'CUST-', got: {code}"
    assert len(code) == 13, f"Code should be 13 chars, got {len(code)}: {code}"
    assert code[5:].isalnum(), f"Suffix should be alphanumeric, got: {code[5:]}"


def test_generate_customer_code_is_unique_across_calls() -> None:
    """Multiple calls should produce different codes (collision-resistant).

    We generate 1000 codes and verify all are unique. With 8 alphanumeric
    characters (36^8 ≈ 2.8 trillion combinations), collisions are extremely unlikely.
    """
    # Arrange
    # (no setup needed)

    # Act
    codes = [generate_customer_code() for _ in range(1000)]

    # Assert
    assert len(set(codes)) == 1000, "All 1000 codes should be unique"


def test_generate_customer_code_uses_injected_random_bytes() -> None:
    """For testability, we can inject the random source.

    This allows deterministic testing by providing fixed bytes.
    """
    # Arrange
    fixed_bytes = b"ABCDEFGH"  # 8 bytes

    # Act
    code1 = generate_customer_code(random_bytes=fixed_bytes)
    code2 = generate_customer_code(random_bytes=fixed_bytes)

    # Assert: same input produces same output (deterministic)
    assert code1 == code2, "Same random_bytes should produce same code"
    assert code1.startswith("CUST-"), f"Format should be preserved: {code1}"


# === Service Order Number Tests ===


def test_generate_service_order_number_has_correct_format() -> None:
    """Service order number must be SO-YYYYMMDD-XXXXXX.

    Format breakdown:
    - SO- prefix (3 chars)
    - YYYYMMDD date (8 chars)
    - - separator (1 char)
    - XXXXXX random suffix (6 chars)
    Total: 18 characters
    """
    # Arrange
    today = date(2026, 1, 9)

    # Act
    order_number = generate_service_order_number(today=today)

    # Assert
    assert order_number.startswith("SO-20260109-"), (
        f"Should start with SO-20260109-, got: {order_number}"
    )
    assert len(order_number) == 18, f"Should be 18 chars, got {len(order_number)}"
    assert order_number[12:].isalnum(), f"Suffix should be alphanumeric: {order_number}"


def test_generate_service_order_number_uses_provided_date() -> None:
    """Date should be injectable for deterministic testing."""
    # Arrange
    test_date = date(2025, 12, 31)

    # Act
    order_number = generate_service_order_number(today=test_date)

    # Assert
    assert "20251231" in order_number, f"Date 20251231 should be in: {order_number}"


def test_generate_service_order_number_unique_on_same_day() -> None:
    """Multiple orders on same day should have different numbers.

    With 6 alphanumeric characters (36^6 ≈ 2.2 billion), we can handle
    many orders per day without collisions.
    """
    # Arrange
    today = date(2026, 1, 9)

    # Act
    numbers = [generate_service_order_number(today=today) for _ in range(1000)]

    # Assert
    assert len(set(numbers)) == 1000, "All 1000 order numbers should be unique"


# === Placeholder VIN Tests ===


def test_generate_placeholder_vin_has_correct_format() -> None:
    """Placeholder VIN must be NO-VIN- followed by 8 hex chars from a UUID.

    Format: NO-VIN-xxxxxxxx (lowercase hex for UUID compatibility).
    This is short enough for voice + DB, but unique enough for MVP.
    """
    # Act
    vin = generate_placeholder_vin()

    # Assert
    # Reason: We use UUID hex prefix for uniqueness without full VIN length.
    assert re.fullmatch(r"NO-VIN-[0-9a-f]{8}", vin) is not None, (
        f"Should match NO-VIN-[8 hex chars], got: {vin}"
    )


def test_generate_placeholder_vin_is_unique_across_calls() -> None:
    """Multiple placeholder VINs should be unique.

    With 8 hex characters (16^8 = 4.3 billion combinations),
    collisions are extremely unlikely.
    """
    # Act
    vins = [generate_placeholder_vin() for _ in range(1000)]

    # Assert
    assert len(set(vins)) == 1000, "All 1000 placeholder VINs should be unique"
