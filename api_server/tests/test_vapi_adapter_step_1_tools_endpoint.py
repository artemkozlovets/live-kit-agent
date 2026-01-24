"""TDD Step 1: Vapi tools endpoint exists in api_server app.

This is the first (simplest) happy-path test for the migration:
- `api_server.server.fastapi_app` must expose `POST /vapi/tools`
- it must return a Vapi-compatible `{ "results": [...] }` response
"""

import json

from fastapi.testclient import TestClient


def test_vapi_tools_endpoint_exists_and_returns_vapi_results_format() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-call-123"},
            "toolCallList": [
                {
                    "id": "tool-call-1",
                    "function": {
                        "name": "validate_phone",
                        "arguments": json.dumps({"phone_number": "3053179840"}),
                    },
                }
            ],
            "assistant": {"extractedVariables": {}},
        }
    }

    # Act
    response = test_client.post("/vapi/tools", json=vapi_tool_call_payload)

    # Assert
    assert response.status_code == 200

    response_data = response.json()
    assert "results" in response_data
    assert len(response_data["results"]) == 1

    result = response_data["results"][0]
    assert result["toolCallId"] == "tool-call-1"

    # Reason: Vapi expects result to be JSON-stringified.
    json.loads(result["result"])

