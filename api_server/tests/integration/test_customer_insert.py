"""Integration tests for customer field mapping and code generation.

Phase 6 of the TDD plan: Verify that API field names are correctly mapped
to Postgres column names when inserting customers, and that customer codes
are auto-generated.

Key mappings tested:
- email_address → email (DB column name)
- Auto-generated customer_code (CUST-XXXXXXXX format)

These tests require a real database connection via DATABASE_URL.
"""

import os

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


# =============================================================================
# TEST 6.4.1: Customer code generation
# =============================================================================
def test_create_customer_generates_unique_customer_code(db_connection) -> None:
    """Customer creation should auto-generate CUST-XXXXXXXX code.

    Format: CUST-XXXXXXXX where XXXXXXXX is 8 random alphanumeric chars.
    Total length: 13 characters.
    """
    # Arrange
    from api_server.models.new_customer_models import NewCustomerArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    # Reason: Generate unique phone to avoid constraint violations
    import uuid

    unique_suffix = uuid.uuid4().hex[:8]
    phone = f"+1555{unique_suffix[:7]}"

    args = NewCustomerArgs(
        first_name="John",
        last_name="Doe",
        company_name="Test Co",
        email_address="john.doe@example.com",
        phone_number=phone,
        streetAddress="123 Main St",
        city="Denver",
        state="CO",
        postalCode="80202",
    )

    # Act
    customer_id = db_client.create_customer(args)

    # Assert
    cursor = db_connection.cursor()
    # Reason: Actual DB uses customer_id as primary key
    cursor.execute(
        "SELECT customer_code FROM customers WHERE customer_id = %s",
        (customer_id,),
    )
    result = cursor.fetchone()
    customer_code = result[0]

    # Verify format
    assert customer_code.startswith("CUST-"), f"Expected CUST- prefix, got: {customer_code}"
    assert len(customer_code) == 13, f"Expected 13 chars, got: {len(customer_code)}"


# =============================================================================
# TEST 6.4.2: email_address → email column mapping
# =============================================================================
def test_create_customer_maps_email_address_to_email_column(db_connection) -> None:
    """NewCustomerArgs.email_address should be stored as customers.email in Postgres.

    The API uses "email_address" (more explicit name),
    but the Postgres schema uses "email" (shorter column name).
    """
    # Arrange
    from api_server.models.new_customer_models import NewCustomerArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    import uuid

    unique_suffix = uuid.uuid4().hex[:8]
    phone = f"+1555{unique_suffix[:7]}"

    args = NewCustomerArgs(
        first_name="Jane",
        last_name="Smith",
        company_name="Smith Inc",
        email_address="jane.smith@example.com",  # API field name
        phone_number=phone,
        streetAddress="456 Oak Ave",
        city="Boulder",
        state="CO",
        postalCode="80301",
    )

    # Act
    customer_id = db_client.create_customer(args)

    # Assert: Query DB directly to verify column name
    cursor = db_connection.cursor()
    # Reason: Actual DB uses customer_id as primary key
    cursor.execute(
        "SELECT email FROM customers WHERE customer_id = %s",
        (customer_id,),
    )
    result = cursor.fetchone()

    # Reason: The API's "email_address" should be stored in DB's "email"
    assert result is not None, "Customer not found"
    assert result[0] == "jane.smith@example.com"


# =============================================================================
# Additional: email_address is optional
# =============================================================================
def test_create_customer_handles_null_email_address(db_connection) -> None:
    """Customer can be created without email_address (it's optional).

    Some customers may not provide an email during intake.
    """
    # Arrange
    from api_server.models.new_customer_models import NewCustomerArgs
    from api_server.server.postgres_client import PostgresDatabaseClient

    db_client = PostgresDatabaseClient(db_connection)

    import uuid

    unique_suffix = uuid.uuid4().hex[:8]
    phone = f"+1555{unique_suffix[:7]}"

    args = NewCustomerArgs(
        first_name="Bob",
        last_name="NoEmail",
        company_name="NoEmail Corp",
        email_address=None,  # Optional - not provided
        phone_number=phone,
        streetAddress="789 Pine St",
        city="Fort Collins",
        state="CO",
        postalCode="80521",
    )

    # Act
    customer_id = db_client.create_customer(args)

    # Assert
    cursor = db_connection.cursor()
    # Reason: Actual DB uses customer_id as primary key
    cursor.execute(
        "SELECT email FROM customers WHERE customer_id = %s",
        (customer_id,),
    )
    result = cursor.fetchone()

    # Reason: Null email should be stored as NULL
    assert result is not None, "Customer not found"
    assert result[0] is None
