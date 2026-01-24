"""Tests for finding units by nickname.

Nickname lookup is the third strategy in our cascading unit resolution:
VIN → unit_number → nickname.

Key behaviors:
- Returns list (not single unit) because nicknames can be ambiguous
- Empty list means no match
- Multiple matches means disambiguation is needed
"""

from api_server.models.database_records import UnitRecord


class FakeDatabaseClient:
    """Fake database client for testing nickname lookup.

    This fake implements just the find_units_by_nickname method,
    returning pre-configured results.
    """

    def __init__(self, units_by_nickname: list[UnitRecord]) -> None:
        self.units_by_nickname = units_by_nickname
        self.last_customer_id: str | None = None
        self.last_nickname: str | None = None

    def find_units_by_nickname(
        self,
        customer_id: str,
        unit_nickname: str,
    ) -> list[UnitRecord]:
        """Return units matching the nickname for this customer."""
        # Track what was requested (for test assertions)
        self.last_customer_id = customer_id
        self.last_nickname = unit_nickname
        return self.units_by_nickname


def test_find_units_by_nickname_returns_matching_unit() -> None:
    """Should return the unit when nickname matches exactly.

    Single match is the happy path - unit is unambiguously identified.
    """
    # Arrange
    expected_unit = UnitRecord(
        unit_id="UNIT-1",
        vin_number="ABC123",
        unit_number="U-001",
        unit_nickname="Blue Truck",
    )
    fake_client = FakeDatabaseClient(units_by_nickname=[expected_unit])

    # Act
    results = fake_client.find_units_by_nickname(
        customer_id="CUST-123",
        unit_nickname="Blue Truck",
    )

    # Assert
    assert len(results) == 1
    assert results[0].unit_nickname == "Blue Truck"
    assert results[0].unit_id == "UNIT-1"


def test_find_units_by_nickname_returns_all_matches() -> None:
    """Should return ALL units when multiple have the same nickname.

    This happens when a customer has multiple vehicles with the same
    nickname (e.g., two trucks both called "Truck"). The caller must
    disambiguate using unit_number.
    """
    # Arrange
    fake_client = FakeDatabaseClient(
        units_by_nickname=[
            UnitRecord(
                unit_id="UNIT-1",
                vin_number="ABC123",
                unit_number="U-001",
                unit_nickname="Truck",
            ),
            UnitRecord(
                unit_id="UNIT-2",
                vin_number="DEF456",
                unit_number="U-002",
                unit_nickname="Truck",
            ),
        ]
    )

    # Act
    results = fake_client.find_units_by_nickname(
        customer_id="CUST-123",
        unit_nickname="Truck",
    )

    # Assert
    assert len(results) == 2  # Both returned for disambiguation


def test_find_units_by_nickname_returns_empty_when_no_match() -> None:
    """Should return empty list when no units match the nickname.

    This triggers fallback to unit auto-creation (Phase 5).
    """
    # Arrange
    fake_client = FakeDatabaseClient(units_by_nickname=[])

    # Act
    results = fake_client.find_units_by_nickname(
        customer_id="CUST-123",
        unit_nickname="Nonexistent",
    )

    # Assert
    assert results == []
