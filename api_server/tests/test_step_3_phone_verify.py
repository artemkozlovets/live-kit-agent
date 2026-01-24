from fastapi.testclient import TestClient


def test_phone_verify_valid_phone_returns_true() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    request_payload = {
        "body": {
            "args": {
                "phone_number": "555-123-4567",
            }
        }
    }

    # Act
    response = test_client.post("/phoneVerify", json=request_payload)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"is_phone_valid": True}


def test_phone_verify_invalid_phone_returns_false() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    request_payload = {
        "body": {
            "args": {
                "phone_number": "555",
            }
        }
    }

    # Act
    response = test_client.post("/phoneVerify", json=request_payload)

    # Assert
    assert response.status_code == 400
    assert response.json() == {"is_phone_valid": False}
