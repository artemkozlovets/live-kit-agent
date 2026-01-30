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

from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Backend:
    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {"customer": {"id": "cust_123", "first_name": "Jane"}}


@pytest.mark.asyncio
async def test_openai_realtime_agent_on_enter_greeting_is_uninterruptible() -> None:
    agent = OpenAIRealtimeAgent(
        backend_client=_Backend(),  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number="+15551234567",
    )

    seen_allow_interruptions: list[object] = []

    async with AgentSession() as session:
        def fake_generate_reply(
            *,
            allow_interruptions: object = None,
            **kwargs: Any,
        ) -> None:
            _ = kwargs
            seen_allow_interruptions.append(allow_interruptions)

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

    assert seen_allow_interruptions == [False]

