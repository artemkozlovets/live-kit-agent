from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit.agents import AgentSession, ChatContext  # noqa: E402

from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Backend:
    def __init__(self, case_status: dict[str, Any]) -> None:
        self._case_status = case_status

    async def call_tool(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self._case_status)


class _Msg:
    def __init__(self, text: str) -> None:
        self.text_content = text


@pytest.mark.asyncio
async def test_openai_realtime_agent_skips_recap_after_booking_confirmed() -> None:
    backend = _Backend({"current_phase": "booking", "booking": {"status": "confirmed"}})
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: str | None = None, **_kwargs: Any) -> None:
            assert isinstance(instructions, str)
            assert "Recap policy (booking)" not in instructions
            assert "Recap policy (post-confirmation)" in instructions

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hello"))


@pytest.mark.asyncio
async def test_openai_realtime_agent_skips_recap_when_user_confirms_booking() -> None:
    backend = _Backend(
        {"current_phase": "booking", "booking": {"status": "pending"}, "message_category": "confirmation"}
    )
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: str | None = None, **_kwargs: Any) -> None:
            assert isinstance(instructions, str)
            assert "Recap policy (booking)" not in instructions
            assert "Recap policy (booking response)" in instructions

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Yes"))


@pytest.mark.asyncio
async def test_openai_realtime_agent_skips_recap_when_user_declines_booking() -> None:
    backend = _Backend(
        {"current_phase": "booking", "booking": {"status": "pending"}, "message_category": "decline"}
    )
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: str | None = None, **_kwargs: Any) -> None:
            assert isinstance(instructions, str)
            assert "Recap policy (booking)" not in instructions
            assert "Recap policy (booking response)" in instructions

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("No"))

