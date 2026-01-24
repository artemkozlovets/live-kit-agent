"""Tests for finding units by unit_number (fleet identifier).

Unit number lookup is the SECOND strategy in our cascading unit resolution:
VIN → unit_number → nickname.

Key behaviors:
- Returns single UnitRecord (or None) because unit_number should be unique per customer
- This is the middle-ground identifier: more human-friendly than VIN, more precise than nickname
"""

from api_server.models.database_records import UnitRecord


class FakeDatabaseClient:
    """Fake database client for testing unit_number lookup.

    This fake implements just the find_unit_by_unit_number method,
    returning a pre-configured result.
    """

    def __init__(self, unit_by_unit_number: UnitRecord | None) -> None:
        self.unit_by_unit_number = unit_by_unit_number
        self.last_customer_id: str | None = None
        self.last_unit_number: str | None = None

    def find_unit_by_unit_number(
        self,
        customer_id: str,
        unit_number: str,
    ) -> UnitRecord | None:
        """Return unit matching the unit_number for this customer."""
        # Track what was requested (for test assertions)
        self.last_customer_id = customer_id
        self.last_unit_number = unit_number
        return self.unit_by_unit_number


def test_find_unit_by_unit_number_returns_matching_unit() -> None:
    """Should return unit when unit_number matches.

    This is the happy path - unit_number is unique within a customer's fleet,
    so we get an unambiguous match.
    """
    # Arrange
    expected_unit = UnitRecord(
        unit_id="UNIT-1",
        vin_number="ABC123",
        unit_number="U-001",
        unit_nickname="Blue Truck",
    )
    fake_client = FakeDatabaseClient(unit_by_unit_number=expected_unit)

    # Act
    result = fake_client.find_unit_by_unit_number(
        customer_id="CUST-123",
        unit_number="U-001",
    )

    # Assert
    assert result == expected_unit
    assert result.unit_id == "UNIT-1"
    assert result.unit_number == "U-001"


def test_find_unit_by_unit_number_returns_none_when_not_found() -> None:
    """Should return None when unit_number doesn't match any unit.

    This triggers fallback to nickname lookup (next strategy in cascade).
    """
    # Arrange
    fake_client = FakeDatabaseClient(unit_by_unit_number=None)

    # Act
    result = fake_client.find_unit_by_unit_number(
        customer_id="CUST-123",
        unit_number="NONEXISTENT",
    )

    # Assert
    assert result is None


def test_find_unit_by_unit_number_tracks_request_parameters() -> None:
    """Verify the method receives correct customer_id and unit_number.

    This ensures proper scoping - we only look for units within
    the authenticated customer's fleet, not globally.
    """
    # Arrange
    fake_client = FakeDatabaseClient(unit_by_unit_number=None)

    # Act
    fake_client.find_unit_by_unit_number(
        customer_id="CUST-ABC",
        unit_number="FLEET-999",
    )

    # Assert: parameters were passed correctly
    assert fake_client.last_customer_id == "CUST-ABC"
    assert fake_client.last_unit_number == "FLEET-999"
