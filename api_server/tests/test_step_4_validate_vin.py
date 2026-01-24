from fastapi.testclient import TestClient


def test_validate_vin_valid_vin_returns_true() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    request_payload = {
        "body": {
            "args": {
                # Example VIN commonly used in validation examples.
                "vin_number": "1HGCM82633A004352",
            }
        }
    }

    # Act
    response = test_client.post("/validateVIN", json=request_payload)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"is_vin_valid": True, "vin_number": "1HGCM82633A004352"}


def test_validate_vin_invalid_vin_returns_false() -> None:
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
    response = test_client.post("/validateVIN", json=request_payload)

    # Assert
    assert response.status_code == 400
    assert response.json() == {"is_vin_valid": False, "vin_number": "INVALID"}
