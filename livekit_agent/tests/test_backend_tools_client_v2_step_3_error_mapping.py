from __future__ import annotations

from typing import Any

import pytest

from livekit_agent.backend_tools_client import BackendToolsClient, BookingNotConfirmedError


@pytest.mark.asyncio
async def test_backend_tools_client_v2_maps_booking_not_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        _ = url
        _ = payload
        _ = headers
        return {
            "results": [
                {
                    "tool_call_id": "tool-call-1",
                    "name": "store_service_order",
                    "ok": False,
                    "error": {"code": "booking_not_confirmed", "message": "User must say yes."},
                }
            ]
        }

    client = BackendToolsClient(tools_url="https://backend.test/tools", post_json=post_json)

    # Act / Assert
    with pytest.raises(BookingNotConfirmedError):
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="store_service_order",
            tool_arguments={},
        )
