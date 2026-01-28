from __future__ import annotations

from typing import Any

import pytest

from livekit_agent.backend_tools_client import BackendToolsClient


@pytest.mark.asyncio
async def test_backend_tools_client_v2_matches_results_by_tool_call_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        _ = url
        _ = payload
        _ = headers
        return {
            "results": [
                {
                    "tool_call_id": "tool-call-other",
                    "name": "get_case_status",
                    "ok": True,
                    "result": {"ok": False},
                },
                {
                    "tool_call_id": "tool-call-1",
                    "name": "get_case_status",
                    "ok": True,
                    "result": {"ok": True},
                },
            ]
        }

    client = BackendToolsClient(tools_url="https://backend.test/tools", post_json=post_json)

    # Act
    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number=None,
        confirmed_callback_number=None,
        tool_call_id="tool-call-1",
        tool_name="get_case_status",
        tool_arguments={"last_user_message": "Hi"},
    )

    # Assert
    assert result == {"ok": True}
