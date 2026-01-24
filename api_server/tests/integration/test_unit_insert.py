"""Integration tests for unit field mapping.

Phase 3.4 of the TDD plan: Verify that API field names are correctly mapped
to Postgres column names when inserting units.

Key mappings tested:
- vin_number → vin (DB column name)
- unit_nickname → unit_nickname (stored directly)

These tests require a real database connection via DATABASE_URL.
"""

import os
import uuid

import psycopg2
import pytest

# Reason: Skip these tests if no database connection is configured.
# In CI or local dev without DB, we skip rather than fail.
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set - skipping integration tests",
)


@pytest.fixture
def db_connection():
    """Create a database connection for testing.

    Uses DATABASE_URL environment variable.
    Connection is closed after each test.
    """
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    yield conn
    conn.close()


@pytest.fixture
def test_customer_id(db_connection) -> str:
    """Create a test customer and return its ID.

    The customer is created for each test to ensure isolation.
    Uses a unique phone number to avoid conflicts.
    """
    cursor = db_connection.cursor()

    # Reason: Generate unique phone to avoid constraint violations
    unique_suffix = uuid.uuid4().hex[:8]
    phone = f"+1555{unique_suffix[:7]}"

    # Reason: Actual DB uses contact_name, phone_number, address_line1, zip_code columns
    cursor.execute(
        """
        INSERT INTO customers (
            contact_name, company_name, phone_number, email,
            address_line1, city, state, zip_code, customer_code
        ) VALUES (
            'Test Customer', 'Test Co', %s, 'test@example.com',
            '123 Main St', 'Denver', 'CO', '80202', %s
        )
        RETURNING customer_id
        """,
        (phone, f"CUST-{unique_suffix}"),
    )
    customer_id = cursor.fetchone()[0]
    db_connection.commit()
    return str(customer_id)


# =============================================================================
# TEST 3.4.1: vin_number → vin column mapping
# =============================================================================
def test_create_unit_maps_vin_number_to_vin_column(
    db_connection, test_customer_id: str
) -> None:
    """StoreUnitArgs.vin_number should be stored as units.vin in Postgres.

    The API uses "vin_number" (more explicit name, consistent with VAPI tools),
    but the Postgres schema uses "vin" (shorter column name).
    This mapping happens in PostgresDatabaseClient.create_unit().
    """
    # Arrange: import the client (which does the mapping)
    from api_server.models.store_unit_models import StoreUnitArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    # Reason: Generate unique VIN to avoid constraint violations
    unique_vin = f"1HGCM{uuid.uuid4().hex[:12].upper()}"

    store_unit_args = StoreUnitArgs(
        first_name="John",
        last_name="Doe",
        company_name="Test Co",
        phone_number="+15551234567",
        vin_number=unique_vin,  # API field name
        unit_number="FLEET-001",
        unit_nickname="Blue Truck",
    )

    # Act: create the unit
    unit_id = db_client.create_unit(store_unit_args, customer_id=test_customer_id)

    # Assert: Query DB directly to verify column name
    cursor = db_connection.cursor()
    # Reason: Actual DB uses unit_id as primary key
    cursor.execute(
        "SELECT vin, unit_nickname FROM units WHERE unit_id = %s",
        (unit_id,),
    )
    result = cursor.fetchone()

    # Reason: The API's "vin_number" should be stored in DB's "vin"
    assert result is not None, "Unit not found"
    vin, unit_nickname = result
    assert vin == unique_vin
    assert unit_nickname == "Blue Truck"


# =============================================================================
# TEST 3.4.2: unit_nickname stored correctly
# =============================================================================
def test_create_unit_stores_nickname(db_connection, test_customer_id: str) -> None:
    """unit_nickname should be stored directly in the unit_nickname column.

    This test verifies the nickname is preserved through the insert.
    """
    # Arrange
    from api_server.models.store_unit_models import StoreUnitArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    unique_vin = f"2FMDK{uuid.uuid4().hex[:12].upper()}"

    store_unit_args = StoreUnitArgs(
        first_name="Jane",
        last_name="Smith",
        company_name="Smith Inc",
        phone_number="+15559876543",
        vin_number=unique_vin,
        unit_number="FLEET-002",
        unit_nickname="Red Van",  # The nickname we're testing
    )

    # Act
    unit_id = db_client.create_unit(store_unit_args, customer_id=test_customer_id)

    # Assert
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT unit_nickname FROM units WHERE unit_id = %s",
        (unit_id,),
    )
    result = cursor.fetchone()

    assert result is not None, "Unit not found"
    assert result[0] == "Red Van"


# =============================================================================
# TEST 3.4.3: unit_nickname is optional (can be NULL)
# =============================================================================
def test_create_unit_handles_null_nickname(db_connection, test_customer_id: str) -> None:
    """Units can be created without a nickname (it's optional).

    Some callers may only provide VIN and unit_number without a nickname.
    """
    # Arrange
    from api_server.models.store_unit_models import StoreUnitArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    unique_vin = f"3GCPK{uuid.uuid4().hex[:12].upper()}"

    store_unit_args = StoreUnitArgs(
        first_name="Bob",
        last_name="NoNickname",
        company_name="NoNickname Corp",
        phone_number="+15551112222",
        vin_number=unique_vin,
        unit_number="FLEET-003",
        unit_nickname=None,  # No nickname provided
    )

    # Act
    unit_id = db_client.create_unit(store_unit_args, customer_id=test_customer_id)

    # Assert
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT unit_nickname FROM units WHERE unit_id = %s",
        (unit_id,),
    )
    result = cursor.fetchone()

    assert result is not None, "Unit not found"
    # Reason: Null nickname should be stored as NULL in DB
    assert result[0] is None
