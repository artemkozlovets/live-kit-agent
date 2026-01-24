"""Tests for database record dataclasses.

These dataclasses represent rows from the database. The tests verify
that they have the correct fields and handle optional values properly.
"""

from api_server.models.database_records import UnitRecord


def test_unit_record_has_unit_id_and_optional_nickname_fields() -> None:
    """UnitRecord should include unit_id (UUID PK) and optional unit_nickname.

    The unit_id is the actual database primary key (UUID), which is different
    from unit_number (a human-readable fleet identifier).
    """
    # Arrange & Act
    record = UnitRecord(
        unit_id="UNIT-123",
        vin_number="1HGCM82633A123456",
        unit_number="UNIT-001",
        unit_nickname="Blue Truck",
    )

    # Assert
    assert record.unit_id == "UNIT-123"
    assert record.unit_nickname == "Blue Truck"
    assert record.vin_number == "1HGCM82633A123456"
    assert record.unit_number == "UNIT-001"


def test_unit_record_nickname_is_optional() -> None:
    """unit_nickname should be optional (None by default).

    Many units won't have nicknames, especially older fleet entries.
    """
    # Arrange & Act
    record = UnitRecord(
        unit_id="UNIT-123",
        vin_number="1HGCM82633A123456",
        unit_number="UNIT-001",
    )

    # Assert
    assert record.unit_nickname is None
