from __future__ import annotations

import os
import json
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


@pytest.mark.asyncio
async def test_openai_realtime_agent_calls_get_case_status_before_generate_reply() -> None:
    calls: list[str] = []

    backend = _Backend(calls)
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    class _Msg:
        def __init__(self, text: str) -> None:
            self.text_content = text

    async with AgentSession() as session:
        def fake_generate_reply(*, user_input: Any = None, chat_ctx: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            calls.append("generate_reply")
            assert user_input == "Hello"
            assert chat_ctx is not None
            items = getattr(chat_ctx, "items", [])
            assert any(
                getattr(item, "role", None) == "system"
                and "case_status" in json.dumps(getattr(item, "content", []))
                for item in items
            )

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hello"))

    assert calls[:2] == ["get_case_status", "generate_reply"]

