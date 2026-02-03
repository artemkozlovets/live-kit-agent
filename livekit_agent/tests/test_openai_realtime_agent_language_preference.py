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
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self._calls.append(str(kwargs.get("tool_name")))
        return {"current_phase": "customer_intake"}


class _Msg:
    def __init__(self, text: str) -> None:
        self.text_content = text


@pytest.mark.asyncio
async def test_language_offer_on_spanish_then_switches_on_confirmation() -> None:
    events: list[str] = []
    replies: list[dict[str, Any]] = []

    backend = _Backend(events)
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            events.append("generate_reply")
            replies.append({"user_input": user_input, "chat_ctx": chat_ctx, **kwargs})

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)

        await agent.on_user_turn_completed(ChatContext(), _Msg("Hola, necesito ayuda con mi carro"))
        assert events[:2] == ["get_case_status", "generate_reply"]
        assert "Language:" in str(replies[-1].get("instructions"))
        assert "English" in str(replies[-1].get("instructions"))
        assert "Would you prefer to speak in Spanish" in str(replies[-1].get("instructions"))

        await agent.on_user_turn_completed(ChatContext(), _Msg("sí"))
        assert events.count("get_case_status") == 1
        assert events.count("generate_reply") == 2
        assert "Spanish" in str(replies[-1].get("instructions"))


@pytest.mark.asyncio
async def test_language_switches_to_spanish_on_explicit_request() -> None:
    events: list[str] = []
    replies: list[dict[str, Any]] = []

    backend = _Backend(events)
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            events.append("generate_reply")
            replies.append({"user_input": user_input, "chat_ctx": chat_ctx, **kwargs})

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Can we do this in Spanish?"))

    assert events == ["generate_reply"]
    assert "Spanish" in str(replies[-1].get("instructions"))


@pytest.mark.asyncio
async def test_language_offer_decline_stays_english() -> None:
    events: list[str] = []
    replies: list[dict[str, Any]] = []

    backend = _Backend(events)
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            events.append("generate_reply")
            replies.append({"user_input": user_input, "chat_ctx": chat_ctx, **kwargs})

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)

        await agent.on_user_turn_completed(ChatContext(), _Msg("Hola, necesito ayuda"))
        assert events[:2] == ["get_case_status", "generate_reply"]

        await agent.on_user_turn_completed(ChatContext(), _Msg("No, English"))

    assert events.count("get_case_status") == 1
    assert events.count("generate_reply") == 2
    assert "English" in str(replies[-1].get("instructions"))


@pytest.mark.asyncio
async def test_language_offer_does_not_auto_switch_without_confirmation() -> None:
    events: list[str] = []
    replies: list[dict[str, Any]] = []

    backend = _Backend(events)
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            events.append("generate_reply")
            replies.append({"user_input": user_input, "chat_ctx": chat_ctx, **kwargs})

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hola, necesito ayuda"))
        await agent.on_user_turn_completed(ChatContext(), _Msg("Necesito una grúa"))

    assert events.count("get_case_status") == 2
    assert events.count("generate_reply") == 2
    assert "English" in str(replies[-1].get("instructions"))
