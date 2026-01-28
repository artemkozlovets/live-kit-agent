from __future__ import annotations

from typing import Any

import pytest

from livekit_agent.backend_tools_client import BackendToolsClient


@pytest.mark.asyncio
async def test_backend_tools_client_v2_sends_v2_payload_and_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        assert url.endswith("/tools")
        assert payload["call"]["id"] == "room-1"

        tool_call = payload["tool_calls"][0]
        assert isinstance(tool_call["arguments"], dict)

        assert headers is not None
        assert headers.get("X-TOOLS-TOKEN") == "test-secret"

        return {
            "results": [
                {
                    "tool_call_id": "tool-call-1",
                    "name": "validate_phone",
                    "ok": True,
                    "result": {"ok": True},
                }
            ]
        }

    client = BackendToolsClient(
        tools_url="https://backend.test/tools",
        post_json=post_json,
    )

    # Act
    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_call_id="tool-call-1",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+15551230000"},
    )

    # Assert
    assert result == {"ok": True}
