from fastapi.testclient import TestClient

from api_server.models.database_records import UnitRecord
from api_server.server.dependencies import get_database_client


class FakeDatabaseClient:
    def __init__(self, units_by_vin_number: dict[str, UnitRecord]) -> None:
        self.units_by_vin_number = units_by_vin_number

    def find_unit_by_vin_number(self, check_vin_args) -> UnitRecord | None:
        return self.units_by_vin_number.get(check_vin_args.vin_number)


def test_check_vin_existing_unit_returns_true() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    unit_record = UnitRecord(
        unit_id="UNIT-1-ID",
        vin_number="1HGCM82633A004352",
        unit_number="UNIT-1",
    )

    fake_database_client = FakeDatabaseClient(
        units_by_vin_number={
            "1HGCM82633A004352": unit_record,
        }
    )

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "vin_number": "1HGCM82633A004352",
                }
            }
        }

        # Act
        response = test_client.post("/checkVin", json=request_payload)

        # Assert
        assert response.status_code == 200
        assert response.json() == {
            "vin_number": "1HGCM82633A004352",
            "unit_number": "UNIT-1",
            "is_in_database": True,
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_check_vin_missing_unit_returns_false() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    fake_database_client = FakeDatabaseClient(units_by_vin_number={})

    app.dependency_overrides[get_database_client] = lambda: fake_database_client
    try:
        test_client = TestClient(app)

        request_payload = {
            "body": {
                "args": {
                    "vin_number": "1HGCM82633A004352",
                }
            }
        }

        # Act
        response = test_client.post("/checkVin", json=request_payload)

        # Assert
        assert response.status_code == 404
        assert response.json() == {
            "vin_number": "1HGCM82633A004352",
            "unit_number": "",
            "is_in_database": False,
        }
    finally:
        app.dependency_overrides.pop(get_database_client, None)


def test_check_vin_invalid_vin_format_returns_bad_request() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    request_payload = {
        "body": {
            "args": {
                "vin_number": "INVALID",
            }
        }
    }

    # Act
    response = test_client.post("/checkVin", json=request_payload)

    # Assert
    assert response.status_code == 400
    assert response.json() == {
        "vin_number": "INVALID",
        "is_in_database": False,
    }
