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
        self.calls.append({"tool_name": kwargs.get("tool_name"), "tool_arguments": kwargs.get("tool_arguments")})
        return {"customer": {"id": None, "first_name": None}}


@pytest.mark.asyncio
async def test_realtime_transcript_matching_phone_greeting_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the test fast and deterministic.
    monkeypatch.setenv("REALTIME_TRANSCRIPT_DEBOUNCE_S", "0.05")
    monkeypatch.setenv("REALTIME_TRANSCRIPT_POST_SILENCE_S", "0.0")
    monkeypatch.setenv("REALTIME_TRANSCRIPT_MAX_WAIT_S", "0.2")

    backend = _Backend()
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number="+15551234567",
    )

    seen_instructions: list[str] = []
    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            if instructions is not None:
                seen_instructions.append(str(instructions))

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

        assert backend.calls == [{"tool_name": "get_case_status", "tool_arguments": {"last_user_message": " "}}]
        assert seen_instructions

        # The greeting is emitted as "Say exactly: ...", but the transcript would be the spoken content only.
        combined = seen_instructions[-1]
        marker = "Say exactly:"
        idx = combined.lower().find(marker.lower())
        assert idx != -1
        spoken = combined[idx + len(marker) :].strip()

        class _Ev:
            pass

        ev = _Ev()
        ev.is_final = True
        ev.transcript = spoken
        ev.created_at = 123.0
        session.emit("user_input_transcribed", ev)  # type: ignore[arg-type]

        # If the transcript were not filtered, we'd expect an additional get_case_status call.
        await asyncio.sleep(0.25)

    assert backend.calls == [{"tool_name": "get_case_status", "tool_arguments": {"last_user_message": " "}}]

