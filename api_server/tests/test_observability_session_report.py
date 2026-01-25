import os

from fastapi.testclient import TestClient


def test_session_report_happy_path_round_trip() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    # Arrange
    old_token = os.environ.get("SESSION_REPORTS_TOKEN")
    os.environ["SESSION_REPORTS_TOKEN"] = "test-token"
    payload = {"room_name": "room-123", "report": {"hello": "world"}}

    try:
        # Act
        post_resp = client.post(
            "/observability/session-report",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )

        # Assert
        assert post_resp.status_code == 200
        assert post_resp.json() == {"ok": True}

        get_resp = client.get(
            "/observability/session-report/room-123",
            headers={"Authorization": "Bearer test-token"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["room_name"] == "room-123"
        assert get_resp.json()["report"] == {"hello": "world"}
    finally:
        if old_token is None:
            os.environ.pop("SESSION_REPORTS_TOKEN", None)
        else:
            os.environ["SESSION_REPORTS_TOKEN"] = old_token


def test_session_report_can_list_reports() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    old_token = os.environ.get("SESSION_REPORTS_TOKEN")
    os.environ["SESSION_REPORTS_TOKEN"] = "test-token"
    try:
        payload = {"room_name": "room-list-1", "report": {"hello": "world"}}
        post_resp = client.post(
            "/observability/session-report",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert post_resp.status_code == 200

        list_resp = client.get(
            "/observability/session-report?limit=10",
            headers={"Authorization": "Bearer test-token"},
        )
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert isinstance(body.get("reports"), list)
        assert any(item.get("room_name") == "room-list-1" for item in body["reports"])
    finally:
        if old_token is None:
            os.environ.pop("SESSION_REPORTS_TOKEN", None)
        else:
            os.environ["SESSION_REPORTS_TOKEN"] = old_token


def test_session_report_requires_token_when_configured() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    old_token = os.environ.get("SESSION_REPORTS_TOKEN")
    os.environ["SESSION_REPORTS_TOKEN"] = "test-token"
    try:
        resp = client.post("/observability/session-report", json={"room_name": "room", "report": {}})
        assert resp.status_code == 401
    finally:
        if old_token is None:
            os.environ.pop("SESSION_REPORTS_TOKEN", None)
        else:
            os.environ["SESSION_REPORTS_TOKEN"] = old_token


def test_session_report_rejects_invalid_payload() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    old_token = os.environ.get("SESSION_REPORTS_TOKEN")
    os.environ["SESSION_REPORTS_TOKEN"] = "test-token"
    try:
        resp = client.post(
            "/observability/session-report",
            json={"room_name": "", "report": {}},
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400
    finally:
        if old_token is None:
            os.environ.pop("SESSION_REPORTS_TOKEN", None)
        else:
            os.environ["SESSION_REPORTS_TOKEN"] = old_token
