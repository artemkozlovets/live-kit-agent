"""Tests for unit auto-creation when resolution fails.

Phase 5 of the TDD plan: When resolve_unit returns not_found=True,
resolve_unit_or_create can automatically create a unit with placeholder values.

Key behaviors:
- Creates unit with placeholder VIN (NO-VIN-xxxxxxxx) when VIN not provided
- Sets Unknown make/model and year=0 for auto-created units
- Only creates when auto_create=True (disabled by default)
- Returns unit_id and was_created flag to indicate if creation happened
"""

from api_server.models.check_vin_models import CheckVinArgs
from api_server.models.database_records import UnitAutoCreateResult, UnitRecord
from api_server.models.store_unit_models import StoreUnitArgs
from api_server.vapi.unit_resolution import resolve_unit_or_create


class FakeDatabaseClient:
    """Fake database client for testing auto-creation.

    Supports:
    - All three lookup methods (returning not found to trigger auto-create)
    - create_unit method that captures arguments for verification
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
        # Captured args from create_unit calls
        self.captured_create_args: dict[str, object] = {}
        self.create_unit_called = False

    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None:
        return self.unit_by_vin

    def find_unit_by_unit_number(
        self,
        customer_id: str,
        unit_number: str,
    ) -> UnitRecord | None:
        return self.unit_by_unit_number

    def find_units_by_nickname(
        self,
        customer_id: str,
        unit_nickname: str,
    ) -> list[UnitRecord]:
        return self.units_by_nickname

    def create_unit(self, store_unit_args: StoreUnitArgs, customer_id: str) -> str:
        """Capture args and return a fake unit_id."""
        self.create_unit_called = True
        self.captured_create_args = {
            "vin": store_unit_args.vin_number,
            "unit_number": store_unit_args.unit_number,
            "unit_nickname": store_unit_args.unit_nickname,
            "make": store_unit_args.make,
            "model": store_unit_args.model,
            "year": store_unit_args.year,
            "customer_id": customer_id,
        }
        return "UNIT-NEW"


# =============================================================================
# TEST 5.2.1: Happy Path - Auto-Create with Placeholder VIN
# =============================================================================
def test_auto_create_unit_when_not_found() -> None:
    """When unit not found and auto_create=True, create with placeholders.

    This test verifies:
    - A new unit is created when lookup fails
    - Placeholder VIN is used (NO-VIN-xxxxxxxx format)
    - Provided unit_number and unit_nickname are preserved
    - Result indicates was_created=True
    """
    # Arrange: fake client returns nothing (unit not found)
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[],
    )

    # Act: try to resolve with auto_create=True
    result = resolve_unit_or_create(
        vin_number=None,
        unit_number="U-999",
        unit_nickname="New Truck",
        db_client=fake_client,
        customer_id="CUST-123",
        auto_create=True,
    )

    # Assert: unit was created with placeholder VIN
    assert result.unit_id == "UNIT-NEW"
    assert result.was_created is True
    assert result.error is None

    # Verify create_unit was called with correct args
    assert fake_client.create_unit_called is True
    # Reason: VIN must start with NO-VIN- when not provided
    assert fake_client.captured_create_args["vin"].startswith("NO-VIN-")
    assert fake_client.captured_create_args["unit_number"] == "U-999"
    assert fake_client.captured_create_args["unit_nickname"] == "New Truck"
    assert fake_client.captured_create_args["customer_id"] == "CUST-123"


# =============================================================================
# TEST 5.2.2: Happy Path - Auto-Create with Unknown Make/Model/Year
# =============================================================================
def test_auto_create_unit_uses_unknown_make_model_year() -> None:
    """Auto-created units should have Unknown make/model and year=0.

    When we don't have vehicle details, we use clearly-marked placeholders
    so they're obviously incomplete rather than looking like real data.
    """
    # Arrange: fake client returns nothing (unit not found)
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[],
    )

    # Act: create with minimal info
    result = resolve_unit_or_create(
        vin_number=None,
        unit_number="FLEET-001",
        unit_nickname=None,
        db_client=fake_client,
        customer_id="CUST-123",
        auto_create=True,
    )

    # Assert: placeholder vehicle details were used
    assert result.was_created is True
    assert fake_client.captured_create_args["make"] == "Unknown"
    assert fake_client.captured_create_args["model"] == "Unknown"
    assert fake_client.captured_create_args["year"] == 0


# =============================================================================
# TEST 5.2.3: Edge Case - Auto-Create Disabled (Default Behavior)
# =============================================================================
def test_no_auto_create_when_disabled() -> None:
    """When auto_create=False, should not create unit even if not found.

    By default, auto_create is False. This prevents accidental unit creation
    when the caller just wants to look up an existing unit.
    """
    # Arrange: fake client returns nothing (unit not found)
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=None,
        units_by_nickname=[],
    )

    # Act: resolve without auto_create (or explicit False)
    result = resolve_unit_or_create(
        vin_number=None,
        unit_number="U-999",
        unit_nickname=None,
        db_client=fake_client,
        customer_id="CUST-123",
        auto_create=False,  # Explicit disable
    )

    # Assert: no unit created, error returned
    assert result.unit_id is None
    assert result.was_created is False
    # Reason: Should indicate unit not found rather than silently failing
    assert result.error is not None
    assert "not found" in result.error.lower()
    # create_unit should NOT have been called
    assert fake_client.create_unit_called is False


# =============================================================================
# TEST 5.2.4: Edge Case - Existing Unit Found (No Create Needed)
# =============================================================================
def test_returns_existing_unit_when_found() -> None:
    """When unit is found by any strategy, return it without creating.

    Auto-create should only trigger when ALL lookup strategies fail.
    If we find an existing unit, return its ID.
    """
    # Arrange: unit exists and will be found by unit_number
    existing_unit = UnitRecord(
        unit_id="EXISTING-UNIT-123",
        vin_number="VIN123",
        unit_number="U-001",
        unit_nickname="Blue Truck",
    )
    fake_client = FakeDatabaseClient(
        unit_by_vin=None,
        unit_by_unit_number=existing_unit,  # Found by unit_number
        units_by_nickname=[],
    )

    # Act: resolve with auto_create=True (but unit exists)
    result = resolve_unit_or_create(
        vin_number=None,
        unit_number="U-001",
        unit_nickname=None,
        db_client=fake_client,
        customer_id="CUST-123",
        auto_create=True,
    )

    # Assert: returns existing unit, no creation
    assert result.unit_id == "EXISTING-UNIT-123"
    assert result.was_created is False
    assert result.error is None
    assert fake_client.create_unit_called is False


# =============================================================================
# TEST 5.2.5: Error Case - Ambiguous Nickname Blocks Auto-Create
# =============================================================================
def test_ambiguous_nickname_blocks_auto_create() -> None:
    """When nickname is ambiguous, return error even with auto_create=True.

    If multiple units match the nickname, we can't know which one the user
    means, so we shouldn't create a new one - we need disambiguation.
    """
    # Arrange: two units with same nickname
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

    # Act: resolve with ambiguous nickname
    result = resolve_unit_or_create(
        vin_number=None,
        unit_number=None,
        unit_nickname="Truck",
        db_client=fake_client,
        customer_id="CUST-123",
        auto_create=True,
    )

    # Assert: error with disambiguation info, no creation
    assert result.unit_id is None
    assert result.was_created is False
    assert result.error is not None
    assert "unit_number" in result.error.lower()  # Tells user what to provide
    assert result.matching_units == ["U-001", "U-002"]
    assert fake_client.create_unit_called is False
