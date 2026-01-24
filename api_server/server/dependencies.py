import os
from typing import Protocol

from api_server.models.check_vin_models import CheckVinArgs
from api_server.models.database_records import (
    CustomerRecord,
    ServiceOrderRecord,
    UnitForServiceOrderRecord,
    UnitRecord,
)
from api_server.models.inbound_models import InboundArgs
from api_server.models.new_customer_models import NewCustomerArgs
from api_server.models.store_service_order_models import StoreServiceOrderArgs
from api_server.models.store_unit_models import StoreUnitArgs
from api_server.models.update_number_models import UpdateNumberRequest


class DatabaseClient(Protocol):
    """Protocol defining the database operations required by the API.

    All methods that return records should return None or empty list when not found,
    rather than raising exceptions.
    """

    def find_customer_by_phone_number(self, inbound_args: InboundArgs) -> CustomerRecord | None: ...
    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None: ...
    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None: ...

    # --- Phase 3 & 4: Multi-strategy unit lookup ---
    def find_unit_by_unit_number(self, customer_id: str, unit_number: str) -> UnitRecord | None:
        """Find unit by unit_number (fleet identifier) within a customer's fleet."""
        ...

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str) -> list[UnitRecord]:
        """Find units by nickname. Returns list because nicknames can be ambiguous."""
        ...

    def create_customer(self, new_customer_args: NewCustomerArgs) -> str: ...
    def find_customer_for_unit_creation(self, store_unit_args: StoreUnitArgs) -> str | None: ...
    def create_unit(self, store_unit_args: StoreUnitArgs, customer_id: str) -> str: ...
    def update_customer_phone_number(self, update_number_request: UpdateNumberRequest) -> str | None: ...
    def update_customer(self, customer_id: str, updates: dict[str, object]) -> str | None: ...
    def customer_exists(self, store_service_order_args: StoreServiceOrderArgs) -> bool: ...
    def find_service_order_by_id(self, order_id: str) -> ServiceOrderRecord | None: ...
    def find_unit_for_service_order(
        self, store_service_order_args: StoreServiceOrderArgs
    ) -> UnitForServiceOrderRecord | None: ...
    def update_service_order(self, order_id: str, updates: dict[str, object]) -> str | None: ...
    def create_service_order(self, store_service_order_args: StoreServiceOrderArgs) -> str: ...


class NotImplementedDatabaseClient:
    def find_customer_by_phone_number(self, inbound_args: InboundArgs) -> CustomerRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def find_unit_by_unit_number(self, customer_id: str, unit_number: str) -> UnitRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str) -> list[UnitRecord]:
        raise NotImplementedError("Database client is not configured yet.")

    def create_customer(self, new_customer_args: NewCustomerArgs) -> str:
        raise NotImplementedError("Database client is not configured yet.")

    def find_customer_for_unit_creation(self, store_unit_args: StoreUnitArgs) -> str | None:
        raise NotImplementedError("Database client is not configured yet.")

    def create_unit(self, store_unit_args: StoreUnitArgs, customer_id: str) -> str:
        raise NotImplementedError("Database client is not configured yet.")

    def update_customer_phone_number(self, update_number_request: UpdateNumberRequest) -> str | None:
        raise NotImplementedError("Database client is not configured yet.")

    def update_customer(self, customer_id: str, updates: dict[str, object]) -> str | None:
        raise NotImplementedError("Database client is not configured yet.")

    def customer_exists(self, store_service_order_args: StoreServiceOrderArgs) -> bool:
        raise NotImplementedError("Database client is not configured yet.")

    def find_service_order_by_id(self, order_id: str) -> ServiceOrderRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def find_unit_for_service_order(
        self, store_service_order_args: StoreServiceOrderArgs
    ) -> UnitForServiceOrderRecord | None:
        raise NotImplementedError("Database client is not configured yet.")

    def update_service_order(self, order_id: str, updates: dict[str, object]) -> str | None:
        raise NotImplementedError("Database client is not configured yet.")

    def create_service_order(self, store_service_order_args: StoreServiceOrderArgs) -> str:
        raise NotImplementedError("Database client is not configured yet.")


def get_database_client() -> DatabaseClient:
    """Get the database client.

    Uses PostgresDatabaseClient if DATABASE_URL is set,
    otherwise falls back to NotImplementedDatabaseClient.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Reason: Only import psycopg2 when we actually need it
        import psycopg2

        from api_server.server.postgres_client import PostgresDatabaseClient

        connection = psycopg2.connect(database_url)
        return PostgresDatabaseClient(connection)

    return NotImplementedDatabaseClient()
