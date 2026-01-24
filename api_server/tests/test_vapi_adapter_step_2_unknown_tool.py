"""TDD Step 2: Unknown tool handling.

Vapi expects HTTP 200 with a tool result that contains an error message
instead of a server crash or a 4xx/5xx response.
"""

import json

from fastapi.testclient import TestClient


def test_vapi_tools_unknown_tool_returns_error_in_result() -> None:
    # Arrange
    from api_server.server.fastapi_app import app

    test_client = TestClient(app)

    vapi_tool_call_payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-call-unknown-1"},
            "toolCallList": [
                {
                    "id": "tool-call-unknown-1",
                    "function": {
                        "name": "non_existent_tool",
                        "arguments": json.dumps({"some_arg": "value"}),
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

    first_result = response_data["results"][0]
    assert first_result["toolCallId"] == "tool-call-unknown-1"

    parsed_result = json.loads(first_result["result"])
    assert "error" in parsed_result
    assert "non_existent_tool" in parsed_result["error"]

