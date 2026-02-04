from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit.agents import AgentSession  # noqa: E402

from livekit_agent.backend_tools_client import BookingNotConfirmedError  # noqa: E402
from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Backend:
    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        raise BookingNotConfirmedError("User has not explicitly confirmed the booking.")


@pytest.mark.asyncio
async def test_forward_tool_returns_structured_error_on_booking_not_confirmed() -> None:
    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        await session.start(agent)
        result = await agent.forward_tool(tool_name="store_service_order", tool_arguments={})

    assert result.get("success") is False
    assert "confirm" in str(result.get("error") or "").lower()

