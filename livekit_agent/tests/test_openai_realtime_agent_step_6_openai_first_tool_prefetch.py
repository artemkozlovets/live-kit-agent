from __future__ import annotations

import os
import json
import asyncio
import time
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit.agents import AgentSession, ChatContext  # noqa: E402

from livekit_agent.backend_tools_client import BackendToolsTransportError  # noqa: E402
from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Msg:
    def __init__(self, text: str) -> None:
        self.text_content = text


def _find_tool_prefetch_payload(chat_ctx: Any) -> dict[str, Any]:
    items = getattr(chat_ctx, "items", [])
    for item in items:
        if getattr(item, "role", None) != "system":
            continue
        content = getattr(item, "content", None)
        content_text: str | None = None
        if isinstance(content, str):
            content_text = content
        elif isinstance(content, list) and len(content) == 1 and isinstance(content[0], str):
            content_text = content[0]

        if not isinstance(content_text, str) or '"tool_prefetch"' not in content_text:
            continue
        return json.loads(content_text)
    raise AssertionError("Missing system tool_prefetch message")


class _Backend:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        tool_name = str(kwargs.get("tool_name"))
        self._calls.append(tool_name)
        if tool_name == "validate_phone":
            return {"valid": True, "formatted": "+13053053055"}
        if tool_name == "check_customer":
            return {"found": True, "customer": {"customer_id": "CUST-1", "customer_name": "John Johnson"}}
        raise AssertionError(f"Unexpected tool call: {tool_name}")


@pytest.mark.asyncio
async def test_openai_first_prefetch_calls_validate_then_check_customer() -> None:
    backend_calls: list[str] = []
    backend = _Backend(backend_calls)
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        use_backend_guardrails=False,
    )

    calls: list[str] = []

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            calls.append("generate_reply")
            assert user_input and isinstance(user_input, str)
            assert chat_ctx is not None
            payload = _find_tool_prefetch_payload(chat_ctx)
            tool_prefetch = payload.get("tool_prefetch")
            assert isinstance(tool_prefetch, dict)
            assert "validate_phone" in tool_prefetch
            assert "check_customer" in tool_prefetch

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("My phone number is 305-305-3055."))

    assert backend_calls == ["validate_phone", "check_customer"]
    assert calls == ["generate_reply"]


@pytest.mark.asyncio
async def test_openai_first_prefetch_uses_existing_confirmed_number_for_lookup() -> None:
    backend_calls: list[str] = []

    class _LookupOnlyBackend:
        def __init__(self, calls: list[str]) -> None:
            self._calls = calls

        async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
            tool_name = str(kwargs.get("tool_name"))
            self._calls.append(tool_name)
            assert tool_name == "check_customer"
            args = kwargs.get("tool_arguments") or {}
            assert isinstance(args, dict)
            assert args.get("phone_number") == "+13053053055"
            return {"found": False}

    backend = _LookupOnlyBackend(backend_calls)
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        use_backend_guardrails=False,
        confirmed_callback_number="+13053053055",
    )

    calls: list[str] = []

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            calls.append("generate_reply")
            assert chat_ctx is not None
            payload = _find_tool_prefetch_payload(chat_ctx)
            tool_prefetch = payload.get("tool_prefetch")
            assert isinstance(tool_prefetch, dict)
            assert "check_customer" in tool_prefetch
            assert "validate_phone" not in tool_prefetch

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hello"))

    assert backend_calls == ["check_customer"]
    assert calls == ["generate_reply"]


@pytest.mark.asyncio
async def test_openai_first_prefetch_backend_down_speaks_fallback_once() -> None:
    class _FailingBackend:
        def __init__(self) -> None:
            self.calls = 0

        async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            raise BackendToolsTransportError("backend down")

    backend = _FailingBackend()
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        use_backend_guardrails=False,
    )

    assistant_messages: list[str] = []
    calls: list[str] = []

    async with AgentSession() as session:
        def fake_generate_reply(**kwargs: Any) -> None:
            _ = kwargs
            calls.append("generate_reply")

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        @session.on("conversation_item_added")
        def on_item(ev: Any) -> None:
            item = getattr(ev, "item", None)
            if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
                assistant_messages.append((getattr(item, "text_content", None) or "").strip())

        await session.start(agent)

        await agent.on_user_turn_completed(ChatContext(), _Msg("My phone number is 305-305-3055."))
        await agent.on_user_turn_completed(ChatContext(), _Msg("Still there?"))

        start = time.monotonic()
        while not assistant_messages and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

    assert backend.calls == 1
    assert calls == []
    assert assistant_messages.count("I'm having trouble connecting — please call back.") == 1
