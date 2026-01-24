"""Cascading unit resolution logic.

Implements the multi-strategy lookup described in the spec:
VIN → unit_number → nickname

This module provides the core resolution logic that handlers can use
when they need to identify a unit from various input identifiers.

Phase 5 adds auto-creation: when unit not found, optionally create it
with placeholder values rather than failing the call.
"""

from api_server.models.check_vin_models import CheckVinArgs
from api_server.models.database_records import UnitAutoCreateResult, UnitRecord, UnitResolutionResult
from api_server.models.store_unit_models import StoreUnitArgs
from api_server.server.dependencies import DatabaseClient
from api_server.utils.key_generation import generate_placeholder_vin


def resolve_unit(
    *,
    vin_number: str | None,
    unit_number: str | None,
    unit_nickname: str | None,
    db_client: DatabaseClient,
    customer_id: str,
) -> UnitResolutionResult:
    """Resolve unit using cascading lookup: VIN → unit_number → nickname.

    Tries each strategy in order and returns on first successful match.
    This ensures we use the most precise identifier available.

    Args:
        vin_number: Vehicle Identification Number (most precise)
        unit_number: Fleet identifier like "FLEET-001" (unique per customer)
        unit_nickname: Friendly name like "Blue Truck" (may be ambiguous)
        db_client: Database client for lookups
        customer_id: Customer whose fleet we're searching

    Returns:
        UnitResolutionResult with either:
        - unit + strategy_used (success)
        - error + matching_units (ambiguous nickname)
        - not_found=True (all strategies exhausted)
    """
    # Strategy 1: VIN lookup (most precise)
    # Reason: VIN is globally unique and unambiguous - best identifier if available.
    if vin_number:
        check_vin_args = CheckVinArgs(vin_number=vin_number)
        unit = db_client.find_unit_by_vin_number(check_vin_args)
        if unit is not None:
            return UnitResolutionResult(unit=unit, strategy_used="vin")

    # Strategy 2: unit_number lookup (fleet identifier)
    # Reason: unit_number is unique per customer, more human-friendly than VIN.
    if unit_number:
        unit = db_client.find_unit_by_unit_number(customer_id, unit_number)
        if unit is not None:
            return UnitResolutionResult(unit=unit, strategy_used="unit_number")

    # Strategy 3: nickname lookup (least precise, may be ambiguous)
    # Reason: Nickname is what callers might say in voice ("Blue Truck").
    if unit_nickname:
        units = db_client.find_units_by_nickname(customer_id, unit_nickname)

        if len(units) == 1:
            # Single match - unambiguous, return it
            return UnitResolutionResult(unit=units[0], strategy_used="nickname")

        if len(units) > 1:
            # Multiple matches - ambiguous, need disambiguation
            matching_unit_numbers = [u.unit_number for u in units]
            return UnitResolutionResult(
                unit=None,
                error=f"Multiple units match nickname '{unit_nickname}'. Please provide unit_number to disambiguate.",
                matching_units=matching_unit_numbers,
            )

    # All strategies exhausted - unit not found
    return UnitResolutionResult(not_found=True)


def resolve_unit_or_create(
    *,
    vin_number: str | None,
    unit_number: str | None,
    unit_nickname: str | None,
    db_client: DatabaseClient,
    customer_id: str,
    auto_create: bool = False,
) -> UnitAutoCreateResult:
    """Resolve unit using cascading lookup, optionally auto-creating if not found.

    Extends resolve_unit() with automatic unit creation when lookup fails.
    This keeps the VAPI call flowing rather than failing when unit is new.

    Args:
        vin_number: Vehicle Identification Number (most precise)
        unit_number: Fleet identifier like "FLEET-001" (unique per customer)
        unit_nickname: Friendly name like "Blue Truck" (may be ambiguous)
        db_client: Database client for lookups and creation
        customer_id: Customer whose fleet we're searching/creating in
        auto_create: If True, create unit with placeholders when not found

    Returns:
        UnitAutoCreateResult with:
        - unit_id + was_created=False (existing unit found)
        - unit_id + was_created=True (new unit created)
        - error + matching_units (ambiguous nickname)
        - error (not found and auto_create=False)
    """
    # Step 1: Try to resolve existing unit using Phase 4 cascade.
    resolution = resolve_unit(
        vin_number=vin_number,
        unit_number=unit_number,
        unit_nickname=unit_nickname,
        db_client=db_client,
        customer_id=customer_id,
    )

    # Case 1: Found existing unit - return its ID.
    if resolution.unit is not None:
        return UnitAutoCreateResult(
            unit_id=resolution.unit.unit_id,
            was_created=False,
        )

    # Case 2: Ambiguous nickname - return error with disambiguation info.
    if resolution.error is not None:
        return UnitAutoCreateResult(
            error=resolution.error,
            matching_units=resolution.matching_units,
        )

    # Case 3: Not found - decide whether to create or return error.
    if resolution.not_found:
        if not auto_create:
            return UnitAutoCreateResult(
                error="Unit not found",
            )

        # Auto-create the unit with placeholder values.
        # Reason: Use placeholder VIN if not provided (NO-VIN-xxxxxxxx format).
        effective_vin = vin_number if vin_number else generate_placeholder_vin()

        # Reason: For auto-created units, use clearly-marked placeholder values
        # so they're obviously incomplete rather than looking like real data.
        store_unit_args = StoreUnitArgs(
            # Customer fields - use placeholders (the customer_id links correctly)
            first_name="Placeholder",
            last_name="Placeholder",
            company_name="Auto-created",
            phone_number="0000000000",
            # Unit identifiers
            vin_number=effective_vin,
            unit_number=unit_number,
            unit_nickname=unit_nickname,
            # Vehicle details - clearly marked as unknown
            make="Unknown",
            model="Unknown",
            year=0,
        )

        unit_id = db_client.create_unit(store_unit_args, customer_id)
        return UnitAutoCreateResult(
            unit_id=unit_id,
            was_created=True,
        )

    # Reason: This should never happen - resolve_unit always sets one of the flags.
    return UnitAutoCreateResult(error="Unexpected resolution state")
