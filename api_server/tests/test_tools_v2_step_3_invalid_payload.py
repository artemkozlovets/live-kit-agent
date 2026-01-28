from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        (
            {
                "call": {},
                "tool_calls": [],
            },
            "missing_call_id",
        ),
        (
            {
                "call": {"id": "call-tools-v2-invalid"},
                "tool_calls": "not-a-list",
            },
            "tool_calls_not_list",
        ),
    ],
)
def test_tools_v2_invalid_payload_returns_400(payload, label) -> None:
    _ = label
    # Arrange
    import os

    os.environ["TOOLS_TOKEN"] = "test-secret"

    from api_server.server.fastapi_app import app

    client = TestClient(app)

    # Act
    response = client.post("/tools", json=payload, headers={"X-TOOLS-TOKEN": "test-secret"})

    # Assert
    assert response.status_code == 400
