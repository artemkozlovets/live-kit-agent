from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    customer_name: str
    phone_number: str
    email: str | None = None
    company_name: str | None = None


@dataclass(frozen=True)
class UnitRecord:
    """Represents a unit (vehicle) record from the database.

    Attributes:
        unit_id: Database primary key (UUID). This is the real DB identifier.
        vin_number: Vehicle Identification Number.
        unit_number: Human-readable fleet identifier (e.g., "FLEET-001").
        unit_nickname: Optional friendly name (e.g., "Blue Truck").
    """

    unit_id: str
    vin_number: str
    unit_number: str
    unit_nickname: str | None = None


@dataclass(frozen=True)
class UnitForServiceOrderRecord:
    unit_id: str
    customer_id: str


@dataclass(frozen=True)
class ServiceOrderRecord:
    service_order_id: str
    customer_id: str
    unit_id: str


@dataclass
class UnitResolutionResult:
    """Result of attempting to resolve a unit through cascading strategies.

    Used by resolve_unit() which tries: VIN → unit_number → nickname.

    Attributes:
        unit: The resolved UnitRecord (None if not found or error)
        strategy_used: Which lookup strategy succeeded ("vin", "unit_number", "nickname")
        error: Human-readable error message if resolution failed
        not_found: True if all strategies were tried and none found a match
        matching_units: For ambiguous nickname, list of unit_numbers to help disambiguate
    """

    unit: UnitRecord | None = None
    strategy_used: str | None = None
    error: str | None = None
    not_found: bool = False
    matching_units: list[str] | None = None


@dataclass
class UnitAutoCreateResult:
    """Result of resolving or auto-creating a unit.

    Used by resolve_unit_or_create() which extends resolve_unit() with
    automatic unit creation when no existing unit is found.

    Attributes:
        unit_id: Database primary key of the resolved or created unit.
        was_created: True if a new unit was created (vs found existing).
        error: Human-readable error if resolution/creation failed.
        matching_units: For ambiguous nickname, list of unit_numbers to help disambiguate.
    """

    unit_id: str | None = None
    was_created: bool = False
    error: str | None = None
    matching_units: list[str] | None = None
