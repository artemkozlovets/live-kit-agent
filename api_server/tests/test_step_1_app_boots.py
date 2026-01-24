from fastapi.testclient import TestClient


def test_health_check_returns_healthy_status() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    # Act
    response = test_client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_swagger_docs_are_reachable() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    # Act
    response = test_client.get("/docs")

    # Assert
    assert response.status_code == 200
