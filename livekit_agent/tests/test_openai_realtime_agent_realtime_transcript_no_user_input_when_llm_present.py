from __future__ import annotations

import asyncio
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
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {
                "tool_name": kwargs.get("tool_name"),
                "tool_arguments": kwargs.get("tool_arguments"),
            }
        )
        return {"current_phase": "customer_intake"}


@pytest.mark.asyncio
async def test_realtime_transcript_turn_does_not_duplicate_user_input_when_llm_present() -> None:
    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    reply_called = asyncio.Event()
    seen_user_input: Any = "unset"

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, **kwargs: Any) -> None:
            nonlocal seen_user_input
            _ = kwargs
            seen_user_input = user_input
            reply_called.set()

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]
        session._llm = object()  # type: ignore[attr-defined]  # Simulate realtime session (AgentSession.llm is read-only).

        await session.start(agent)
        await agent.on_enter()

        class _Ev:
            pass

        ev = _Ev()
        ev.is_final = True
        ev.transcript = "Hello"
        ev.created_at = 123.0
        session.emit("user_input_transcribed", ev)  # type: ignore[arg-type]

        await asyncio.wait_for(reply_called.wait(), timeout=2.0)

    assert backend.calls
    assert backend.calls[0]["tool_name"] == "get_case_status"
    assert backend.calls[0]["tool_arguments"] == {"last_user_message": "Hello", "expected_field": None}

    assert seen_user_input is None
