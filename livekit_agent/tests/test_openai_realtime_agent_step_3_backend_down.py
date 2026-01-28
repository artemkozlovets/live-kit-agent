from __future__ import annotations

import os
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


class _FailingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        self.calls += 1
        raise BackendToolsTransportError("backend down")


@pytest.mark.asyncio
async def test_openai_realtime_agent_backend_down_speaks_one_fallback() -> None:
    backend = _FailingBackend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    assistant_messages: list[str] = []
    calls: list[str] = []

    class _Msg:
        def __init__(self, text: str) -> None:
            self.text_content = text

    async with AgentSession() as session:
        def fake_generate_reply(**kwargs: Any) -> None:
            calls.append("generate_reply")
            _ = kwargs

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        @session.on("conversation_item_added")
        def on_item(ev: Any) -> None:
            item = getattr(ev, "item", None)
            if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
                assistant_messages.append((getattr(item, "text_content", None) or "").strip())

        await session.start(agent)

        await agent.on_user_turn_completed(ChatContext(), _Msg("Hello"))
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hello again"))

        start = time.monotonic()
        while not assistant_messages and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

    assert backend.calls == 1
    assert calls == []
    assert assistant_messages.count("I'm having trouble connecting — please call back.") == 1

