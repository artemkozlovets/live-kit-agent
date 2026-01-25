from fastapi.testclient import TestClient


def test_vapi_tools_rejects_empty_body_as_bad_request() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    resp = client.post("/vapi/tools", data="", headers={"Content-Type": "application/json"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid JSON payload"


def test_vapi_tools_rejects_malformed_json_as_bad_request() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    resp = client.post("/vapi/tools", data="{", headers={"Content-Type": "application/json"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid JSON payload"


def test_vapi_tools_rejects_non_object_json_as_bad_request() -> None:
    from api_server.server.fastapi_app import app

    client = TestClient(app)

    resp = client.post("/vapi/tools", json=[])

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid JSON payload"

