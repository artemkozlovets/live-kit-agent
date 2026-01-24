"""Postgres implementation of the DatabaseClient protocol.

This module provides the real database operations for production use.
It maps API field names to Postgres column names and generates unique keys.

Field mappings (API → DB):
- service_complaint → customer_complaint
- service_location → location_address
- email_address → email
- vin_number → vin

Auto-generated fields:
- customer_code: CUST-XXXXXXXX format
- service_order_number: SO-YYYYMMDD-XXXXXX format
"""

from typing import Any

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
from api_server.utils.key_generation import (
    generate_customer_code,
    generate_service_order_number,
)

# Reason: Default status for new service orders (VAPI doesn't send this).
# Valid values: created, assigned, unassigned, in_progress, diagnosing,
# awaiting_parts, awaiting_authorization, authorized, rejected, in_repair,
# quality_review, completed, cancelled, invoiced, on_hold
DEFAULT_SERVICE_ORDER_STATUS = "created"


class PostgresDatabaseClient:
    """Real Postgres database client implementing DatabaseClient protocol.

    Handles field mapping between API models and Postgres schema,
    and auto-generates unique keys where required.
    """

    def __init__(self, connection: Any) -> None:
        """Initialize with a psycopg2 connection.

        Args:
            connection: A psycopg2 database connection.
        """
        self.connection = connection

    def find_customer_by_phone_number(self, inbound_args: InboundArgs) -> CustomerRecord | None:
        """Find customer by phone number.

        Args:
            inbound_args: Contains the phone number to search for.

        Returns:
            CustomerRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses customer_id, contact_name, phone_number columns.
        # We also select optional fields used by get_case_status (email, company_name).
        cursor.execute(
            """
            SELECT customer_id, contact_name, phone_number, email, company_name
            FROM customers
            WHERE phone_number = %s
            """,
            (inbound_args.phone_number,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return CustomerRecord(
            customer_id=str(row[0]),
            customer_name=row[1] or "",
            phone_number=row[2],
            email=row[3] or None,
            company_name=row[4] or None,
        )

    def find_customer_by_id(self, customer_id: str) -> CustomerRecord | None:
        """Find customer by ID.

        Args:
            customer_id: Customer UUID.

        Returns:
            CustomerRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT customer_id, contact_name, phone_number, email, company_name
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return CustomerRecord(
            customer_id=str(row[0]),
            customer_name=row[1] or "",
            phone_number=row[2],
            email=row[3] or None,
            company_name=row[4] or None,
        )

    def find_unit_by_vin_number(self, check_vin_args: CheckVinArgs) -> UnitRecord | None:
        """Find unit by VIN number.

        Args:
            check_vin_args: Contains the VIN to search for.

        Returns:
            UnitRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses unit_id as primary key column name
        cursor.execute(
            """
            SELECT unit_id, vin, unit_number, unit_nickname
            FROM units
            WHERE vin = %s
            """,
            (check_vin_args.vin_number,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return UnitRecord(
            unit_id=str(row[0]),
            vin_number=row[1],
            unit_number=row[2] or "",
            unit_nickname=row[3],
        )

    def find_unit_by_unit_number(self, customer_id: str, unit_number: str) -> UnitRecord | None:
        """Find unit by unit_number within a customer's fleet.

        Args:
            customer_id: The customer's database ID.
            unit_number: The fleet identifier (e.g., "FLEET-001").

        Returns:
            UnitRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses unit_id as primary key column name
        cursor.execute(
            """
            SELECT unit_id, vin, unit_number, unit_nickname
            FROM units
            WHERE customer_id = %s AND unit_number = %s
            """,
            (customer_id, unit_number),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return UnitRecord(
            unit_id=str(row[0]),
            vin_number=row[1],
            unit_number=row[2] or "",
            unit_nickname=row[3],
        )

    def find_units_by_nickname(self, customer_id: str, unit_nickname: str) -> list[UnitRecord]:
        """Find units by nickname. Returns list because nicknames can be ambiguous.

        Args:
            customer_id: The customer's database ID.
            unit_nickname: The friendly name to search for.

        Returns:
            List of matching UnitRecords (empty if none found).
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses unit_id as primary key column name
        cursor.execute(
            """
            SELECT unit_id, vin, unit_number, unit_nickname
            FROM units
            WHERE customer_id = %s AND unit_nickname = %s
            """,
            (customer_id, unit_nickname),
        )
        rows = cursor.fetchall()

        return [
            UnitRecord(
                unit_id=str(row[0]),
                vin_number=row[1],
                unit_number=row[2] or "",
                unit_nickname=row[3],
            )
            for row in rows
        ]

    def create_customer(self, new_customer_args: NewCustomerArgs) -> str:
        """Create a new customer record.

        Field mappings (API → DB):
        - first_name + last_name → contact_name
        - email_address → email
        - phone_number → phone_number (same)
        - streetAddress → address_line1
        - postalCode → zip_code

        Auto-generates:
        - customer_code in CUST-XXXXXXXX format

        Args:
            new_customer_args: Customer details from API.

        Returns:
            The new customer's database ID (as string).
        """
        cursor = self.connection.cursor()

        # Reason: Generate unique customer code to satisfy DB constraint
        customer_code = generate_customer_code()

        # Reason: Combine first_name + last_name into contact_name for the DB
        contact_name = f"{new_customer_args.first_name} {new_customer_args.last_name}"

        # Reason: Actual DB column names differ from API model names
        cursor.execute(
            """
            INSERT INTO customers (
                contact_name, company_name, phone_number, email,
                address_line1, city, state, zip_code, customer_code
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING customer_id
            """,
            (
                contact_name,
                new_customer_args.company_name,
                new_customer_args.phone_number,
                # Reason: Map email_address → email
                new_customer_args.email_address,
                # Reason: Map streetAddress → address_line1
                new_customer_args.streetAddress,
                new_customer_args.city,
                new_customer_args.state,
                # Reason: Map postalCode → zip_code
                new_customer_args.postalCode,
                customer_code,
            ),
        )
        customer_id = cursor.fetchone()[0]
        self.connection.commit()

        return str(customer_id)

    def find_customer_for_unit_creation(self, store_unit_args: StoreUnitArgs) -> str | None:
        """Find customer by phone for unit creation.

        Args:
            store_unit_args: Contains phone_number to search for.

        Returns:
            Customer ID if found, None otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses customer_id, phone_number column names
        cursor.execute(
            "SELECT customer_id FROM customers WHERE phone_number = %s",
            (store_unit_args.phone_number,),
        )
        row = cursor.fetchone()
        return str(row[0]) if row else None

    def create_unit(self, store_unit_args: StoreUnitArgs, customer_id: str) -> str:
        """Create a new unit record.

        Field mappings:
        - vin_number → vin (DB column name)

        Args:
            store_unit_args: Unit details from API.
            customer_id: The customer's database ID.

        Returns:
            The new unit's database ID (as string).
        """
        cursor = self.connection.cursor()

        # Reason: Actual DB uses unit_id as primary key column name
        # Reason: The DB requires make/model/year (NOT NULL), so use safe defaults.
        make = store_unit_args.make or "Unknown"
        model = store_unit_args.model or "Unknown"
        year = store_unit_args.year if store_unit_args.year is not None else 0

        cursor.execute(
            """
            INSERT INTO units (
                customer_id, vin, unit_number, unit_nickname,
                make, model, year
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING unit_id
            """,
            (
                customer_id,
                # Reason: Map vin_number → vin
                store_unit_args.vin_number,
                store_unit_args.unit_number,
                store_unit_args.unit_nickname,
                make,
                model,
                year,
            ),
        )
        unit_id = cursor.fetchone()[0]
        self.connection.commit()

        return str(unit_id)

    def update_customer_phone_number(self, update_number_request: UpdateNumberRequest) -> str | None:
        """Update a customer's phone number.

        Args:
            update_number_request: Contains old and new phone numbers.

        Returns:
            Customer ID if updated, None if customer not found.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses customer_id, phone_number column names
        cursor.execute(
            """
            UPDATE customers
            SET phone_number = %s
            WHERE phone_number = %s
            RETURNING customer_id
            """,
            (update_number_request.new_number, update_number_request.old_number),
        )
        row = cursor.fetchone()
        self.connection.commit()

        return str(row[0]) if row else None

    def update_customer(self, customer_id: str, updates: dict[str, object]) -> str | None:
        """Update a customer's profile fields.

        Args:
            customer_id: Customer UUID to update.
            updates: API-shaped update fields (plus optional contact_name).

        Returns:
            Customer ID if updated, None if customer not found.
        """
        column_map = {
            "contact_name": "contact_name",
            "email_address": "email",
            "phone_number": "phone_number",
            "company_name": "company_name",
            "streetAddress": "address_line1",
            "city": "city",
            "state": "state",
            "postalCode": "zip_code",
        }

        set_clauses: list[str] = []
        values: list[object] = []
        for update_field, column_name in column_map.items():
            if update_field not in updates:
                continue
            value = updates.get(update_field)
            if value is None:
                continue
            set_clauses.append(f"{column_name} = %s")
            values.append(value)

        if not set_clauses:
            return customer_id

        cursor = self.connection.cursor()
        values.append(customer_id)
        cursor.execute(
            f"""
            UPDATE customers
            SET {', '.join(set_clauses)}
            WHERE customer_id = %s
            RETURNING customer_id
            """,
            tuple(values),
        )
        row = cursor.fetchone()
        self.connection.commit()

        return str(row[0]) if row else None

    def customer_exists(self, store_service_order_args: StoreServiceOrderArgs) -> bool:
        """Check if a customer exists by ID.

        Args:
            store_service_order_args: Contains customer_id to check.

        Returns:
            True if customer exists, False otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses customer_id as primary key column name
        cursor.execute(
            "SELECT 1 FROM customers WHERE customer_id = %s",
            (store_service_order_args.customer_id,),
        )
        return cursor.fetchone() is not None

    def find_service_order_by_id(self, order_id: str) -> ServiceOrderRecord | None:
        """Find service order by ID.

        Args:
            order_id: Service order UUID.

        Returns:
            ServiceOrderRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT service_order_id, customer_id, unit_id
            FROM service_orders
            WHERE service_order_id = %s
            """,
            (order_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return ServiceOrderRecord(
            service_order_id=str(row[0]),
            customer_id=str(row[1]),
            unit_id=str(row[2]),
        )

    def find_unit_for_service_order(
        self, store_service_order_args: StoreServiceOrderArgs
    ) -> UnitForServiceOrderRecord | None:
        """Find unit by ID for service order creation.

        Args:
            store_service_order_args: Contains unit_id to search for.

        Returns:
            UnitForServiceOrderRecord if found, None otherwise.
        """
        cursor = self.connection.cursor()
        # Reason: Actual DB uses unit_id as primary key column name
        cursor.execute(
            "SELECT unit_id, customer_id FROM units WHERE unit_id = %s",
            (store_service_order_args.unit_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return UnitForServiceOrderRecord(
            unit_id=str(row[0]),
            customer_id=str(row[1]),
        )

    def update_service_order(self, order_id: str, updates: dict[str, object]) -> str | None:
        """Update a service order.

        Args:
            order_id: Service order UUID.
            updates: API-shaped update fields plus optional unit_id.

        Returns:
            Service order ID if updated, None if not found.
        """
        column_map = {
            "service_location": "location_address",
            "service_complaint": "customer_complaint",
            "unit_id": "unit_id",
        }

        set_clauses: list[str] = []
        values: list[object] = []
        for update_field, column_name in column_map.items():
            if update_field not in updates:
                continue
            value = updates.get(update_field)
            if value is None:
                continue
            set_clauses.append(f"{column_name} = %s")
            values.append(value)

        if not set_clauses:
            return order_id

        cursor = self.connection.cursor()
        values.append(order_id)
        cursor.execute(
            f"""
            UPDATE service_orders
            SET {', '.join(set_clauses)}
            WHERE service_order_id = %s
            RETURNING service_order_id
            """,
            tuple(values),
        )
        row = cursor.fetchone()
        self.connection.commit()

        return str(row[0]) if row else None

    def create_service_order(self, store_service_order_args: StoreServiceOrderArgs) -> str:
        """Create a new service order.

        Field mappings:
        - service_complaint → customer_complaint (DB column name)
        - service_location → location_address (DB column name)

        Auto-generates:
        - service_order_number in SO-YYYYMMDD-XXXXXX format
        - status defaults to "pending"

        Args:
            store_service_order_args: Service order details from API.

        Returns:
            The new service order's database ID (as string).
        """
        cursor = self.connection.cursor()

        # Reason: Generate unique service order number to satisfy DB constraint
        service_order_number = generate_service_order_number()

        # Reason: Actual DB uses service_order_id as primary key column name
        cursor.execute(
            """
            INSERT INTO service_orders (
                customer_id, unit_id, customer_complaint, location_address,
                service_order_number, status
            ) VALUES (
                %s, %s, %s, %s, %s, %s
            )
            RETURNING service_order_id
            """,
            (
                store_service_order_args.customer_id,
                store_service_order_args.unit_id,
                # Reason: Map service_complaint → customer_complaint
                store_service_order_args.service_complaint,
                # Reason: Map service_location → location_address
                store_service_order_args.service_location,
                service_order_number,
                # Reason: VAPI doesn't send status, so we default to "pending"
                DEFAULT_SERVICE_ORDER_STATUS,
            ),
        )
        service_order_id = cursor.fetchone()[0]
        self.connection.commit()

        return str(service_order_id)
