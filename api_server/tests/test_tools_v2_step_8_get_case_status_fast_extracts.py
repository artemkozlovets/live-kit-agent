from __future__ import annotations

from fastapi.testclient import TestClient


def test_tools_v2_get_case_status_fast_path_extracts_fields(monkeypatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    from api_server.server.fastapi_app import app

    client = TestClient(app)
    payload = {
        "call": {"id": "call-tools-v2-fast-extracts"},
        "tool_calls": [
            {
                "id": "tool-call-get-case-status",
                "name": "get_case_status",
                "arguments": {
                    "last_user_message": (
                        "My name is John Smith. I'm at Denver CO. VIN 1HGBH41JXMN109186. "
                        "I have a flat tire. My phone is 305-317-9840."
                    ),
                    "expected_field": None,
                },
            }
        ],
    }

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is True
    result_obj = result["result"]

    customer_known_data = result_obj.get("customer_known_data")
    service = result_obj.get("service")

    extracted_any = False
    if isinstance(customer_known_data, dict):
        extracted_any = extracted_any or any(value for value in customer_known_data.values())
    if isinstance(service, dict):
        extracted_any = extracted_any or any(value for value in service.values())
    assert extracted_any is True

