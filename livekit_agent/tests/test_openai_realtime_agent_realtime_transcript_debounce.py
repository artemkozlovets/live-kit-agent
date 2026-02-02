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
        return {"customer": {"id": None}}


@pytest.mark.asyncio
async def test_realtime_transcript_turn_debounces_bursty_finals() -> None:
    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    reply_called = asyncio.Event()
    seen: list[dict[str, Any]] = []

    async with AgentSession() as session:
        def fake_generate_reply(
            *,
            user_input: Any = None,
            instructions: Any = None,
            **kwargs: Any,
        ) -> None:
            _ = kwargs
            seen.append({"user_input": user_input, "instructions": instructions})
            reply_called.set()

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

        class _Ev:
            pass

        ev1 = _Ev()
        ev1.is_final = True
        ev1.transcript = "Hello"
        ev1.created_at = 123.0
        session.emit("user_input_transcribed", ev1)  # type: ignore[arg-type]

        ev2 = _Ev()
        ev2.is_final = True
        ev2.transcript = "world"
        ev2.created_at = 124.0
        session.emit("user_input_transcribed", ev2)  # type: ignore[arg-type]

        await asyncio.wait_for(reply_called.wait(), timeout=3.0)

    assert backend.calls == [
        {"tool_name": "get_case_status", "tool_arguments": {"last_user_message": "Hello world", "expected_field": None}}
    ]
    assert any(item["user_input"] == "Hello world" for item in seen)


@pytest.mark.asyncio
async def test_realtime_transcript_turn_waits_for_user_to_stop_speaking(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the test fast and deterministic.
    monkeypatch.setenv("REALTIME_TRANSCRIPT_DEBOUNCE_S", "0.05")
    monkeypatch.setenv("REALTIME_TRANSCRIPT_POST_SILENCE_S", "0.0")
    monkeypatch.setenv("REALTIME_TRANSCRIPT_MAX_WAIT_S", "2.0")

    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    reply_called = asyncio.Event()

    async with AgentSession() as session:
        def fake_generate_reply(**kwargs: Any) -> None:
            _ = kwargs
            reply_called.set()

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

        class _UserStateEv:
            pass

        speaking = _UserStateEv()
        speaking.new_state = "speaking"
        session.emit("user_state_changed", speaking)  # type: ignore[arg-type]

        class _TranscriptEv:
            pass

        ev = _TranscriptEv()
        ev.is_final = True
        ev.transcript = "Hello"
        ev.created_at = 123.0
        session.emit("user_input_transcribed", ev)  # type: ignore[arg-type]

        await asyncio.sleep(0.15)
        assert reply_called.is_set() is False

        listening = _UserStateEv()
        listening.new_state = "listening"
        session.emit("user_state_changed", listening)  # type: ignore[arg-type]

        await asyncio.wait_for(reply_called.wait(), timeout=2.0)

