"""Tests for cascading unit resolution.

The resolve_unit function implements the multi-strategy lookup described in spec:
1. VIN (most precise, if provided)
2. unit_number (fleet identifier, if VIN not found)
3. nickname (least precise, may need disambiguation)

Key behaviors:
- Returns the FIRST successful match (stops at first hit)
- Returns real unit_id (database UUID), not human identifiers
- Handles ambiguous nickname matches with helpful error
- Returns not_found when all strategies exhausted
"""

from api_server.models.check_vin_models import CheckVinArgs
from api_server.models.database_records import UnitRecord
from api_server.vapi.unit_resolution import resolve_unit


class FakeDatabaseClient:
    """Fake database client for testing cascading resolution.

    Supports all three lookup methods needed for the cascade:
    - find_unit_by_vin_number (first strategy)
    - find_unit_by_unit_number (second strategy)
    - find_units_by_nickname (third strategy, returns list)
    """

    def __init__(
        self,
        unit_by_vin: UnitRecord | None = None,
        unit_by_unit_number: UnitRecord | None = None,
        units_by_nickname: list[UnitRecord] | None = None,
    ) -> None:
        self.unit_by_vin = unit_by_vin
        self.unit_by_unit_number = unit_by_unit_number
        self.units_by_nickname = units_by_nickname or []
        # Track which methods were called (for verifying short-circuit)
        self.vin_lookup_called = False
        self.unit_number_lookup_called = False
        self.nickname_lookup_called = False

    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None:
        self.vin_lookup_called = True
        return self.unit_by_vin

    def find_unit_by_unit_number(
        self,
        customer_id: str,
        unit_number: str,
    ) -> UnitRecord | None:
        self.unit_number_lookup_called = True
        return self.unit_by_unit_number

    def find_units_by_nickname(
        self,
        customer_id: str,
        unit_nickname: str,
    ) -> list[UnitRecord]:
        self.nickname_lookup_called = True
        return self.units_by_nickname


# =============================================================================
# TEST 4.2.1: Happy Path - VIN Found (First Strategy)
# =============================================================================
def test_resolve_unit_finds_by_vin_first() -> None:
    """When VIN is provided and found, don't try other strategies.

    VIN is the most precise identifier - if it matches, we're done.
    This test also verifies short-circuit behavior (other methods not called).
    """
    # Arrange
    expected_unit = UnitRecord(
        unit_id="UNIT-1",
        vin_number="VIN123",
        unit_number="U-001",
        unit_nickname="Blue Truck",
    )
    fake_client = FakeDatabaseClient(
        unit_by_vin=expected_unit,
        unit_by_unit_number=None,  # Should not be called
        units_by_nickname=[],  # Should not be called
    )

    # Act
    result = resolve_unit(
        vin_number="VIN123",
        unit_number=None,
        unit_nickname=None,
        db_client=fake_client,
        customer_id="CUST-123",
    )

    # Assert
    assert result.unit is not None
    assert result.unit.vin_number == "VIN123"
    assert result.unit.unit_id == "UNIT-1"
    assert result.strategy_used == "vin"
    # Verify short-circuit: other strategies were NOT tried
    assert fake_client.vin_lookup_called is True
    assert fake_client.unit_number_lookup_called is False
    assert fake_client.nickname_lookup_called is False


# =============================================================================
# TEST 4.2.2: Happy Path - VIN Missing, Unit Number Found (Second Strategy)
# =============================================================================
def test_resolve_unit_falls_back_to_unit_number() -> None:
    """When VIN not provided/found, try unit_number.

    unit_number is the fleet identifier (e.g., "FLEET-001") and is unique
    within a customer's fleet.
    """
    # Arrange
    expected_unit = UnitRecord(
        unit_id="UNIT-2",
        vin_number="VIN456",
        unit_number="U-002",
        unit_nickname=None,
    )
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,  # VIN lookup fails
        unit_by_unit_number=expected_unit,  # unit_number lookup succeeds
        units_by_nickname=[],
    )

    # Act
    result = resolve_unit(
        vin_number=None,
        unit_number="U-002",
        unit_nickname=None,
        db_client=fake_client,
        customer_id="CUST-123",
    )

    # Assert
    assert result.unit is not None
    assert result.unit.unit_number == "U-002"
    assert result.unit.unit_id == "UNIT-2"
    assert result.strategy_used == "unit_number"


# =============================================================================
# TEST 4.2.3: Happy Path - Nickname Found (Third Strategy)
# =============================================================================
def test_resolve_unit_falls_back_to_nickname() -> None:
    """When VIN and unit_number not provided/found, try nickname.

    Nickname is the least precise (can be ambiguous), but still useful
    for voice interfaces where users might say "Blue Truck".
    """
    # Arrange
    expected_unit = UnitRecord(
        unit_id="UNIT-3",
        vin_number="VIN789",
        unit_number="U-003",
        unit_nickname="Blue Truck",
    )
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[expected_unit],  # Single match - unambiguous
    )

    # Act
    result = resolve_unit(
        vin_number=None,
        unit_number=None,
        unit_nickname="Blue Truck",
        db_client=fake_client,
        customer_id="CUST-123",
    )

    # Assert
    assert result.unit is not None
    assert result.unit.unit_nickname == "Blue Truck"
    assert result.unit.unit_id == "UNIT-3"
    assert result.strategy_used == "nickname"


# =============================================================================
# TEST 4.2.4: Edge Case - Ambiguous Nickname (Disambiguation Required)
# =============================================================================
def test_resolve_unit_returns_error_for_ambiguous_nickname() -> None:
    """When multiple units match nickname, require unit_number.

    If a customer has two trucks both nicknamed "Truck", we can't know
    which one they mean. Return an error with the unit_numbers for disambiguation.
    """
    # Arrange
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[
            UnitRecord(
                unit_id="UNIT-1",
                vin_number="VIN1",
                unit_number="U-001",
                unit_nickname="Truck",
            ),
            UnitRecord(
                unit_id="UNIT-2",
                vin_number="VIN2",
                unit_number="U-002",
                unit_nickname="Truck",
            ),
        ],
    )

    # Act
    result = resolve_unit(
        vin_number=None,
        unit_number=None,
        unit_nickname="Truck",
        db_client=fake_client,
        customer_id="CUST-123",
    )

    # Assert: should return error with disambiguation info
    assert result.unit is None
    assert result.error is not None
    assert "ambiguous" in result.error.lower() or "multiple" in result.error.lower()
    assert "unit_number" in result.error.lower()  # Tells user what to provide
    assert result.matching_units == ["U-001", "U-002"]  # Helps with disambiguation


# =============================================================================
# TEST 4.2.5: Failure Case - Unit Not Found (All Strategies Exhausted)
# =============================================================================
def test_resolve_unit_returns_not_found_when_all_strategies_fail() -> None:
    """When no strategy finds a unit, return not found.

    This will trigger unit auto-creation in Phase 5.
    """
    # Arrange
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[],
    )

    # Act
    result = resolve_unit(
        vin_number="NONEXISTENT",
        unit_number="NONEXISTENT",
        unit_nickname="NONEXISTENT",
        db_client=fake_client,
        customer_id="CUST-123",
    )

    # Assert
    assert result.unit is None
    assert result.not_found is True
