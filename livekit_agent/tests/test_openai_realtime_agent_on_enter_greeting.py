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

from livekit_agent.backend_tools_client import BackendToolsTransportError  # noqa: E402
from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Backend:
    def __init__(self, response: dict[str, Any]) -> None:
        self.calls: list[str] = []
        self._response = response

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(str(kwargs.get("tool_name")))
        return dict(self._response)


@pytest.mark.asyncio
async def test_openai_realtime_agent_on_enter_greets_known_customer_by_name() -> None:
    backend = _Backend(
        {
            "customer": {"id": "cust_123", "first_name": "Jane"},
        }
    )
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number="+15551234567",
    )

    calls: list[str] = []
    seen_instructions: list[str] = []

    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            calls.append("generate_reply")
            seen_instructions.append(str(instructions or ""))

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

    assert backend.calls == ["get_case_status"]
    assert calls == ["generate_reply"]
    assert any("Hello Jane" in instr for instr in seen_instructions)
    assert any("Sarah" in instr for instr in seen_instructions)
    assert any("+15551234567" in instr for instr in seen_instructions)
    assert any("best number to reach you" in instr.lower() for instr in seen_instructions)


@pytest.mark.asyncio
async def test_openai_realtime_agent_on_enter_handles_unknown_customer() -> None:
    backend = _Backend({"customer": {"id": None, "first_name": None}})
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number="+15551234567",
    )

    seen_instructions: list[str] = []
    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            seen_instructions.append(str(instructions or ""))

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

    assert backend.calls == ["get_case_status"]
    assert len(seen_instructions) == 1
    assert "Hello" in seen_instructions[0]
    assert "Sarah" in seen_instructions[0]


@pytest.mark.asyncio
async def test_openai_realtime_agent_on_enter_falls_back_when_backend_down() -> None:
    class _FailingBackend:
        async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            raise BackendToolsTransportError("backend down")

    agent = OpenAIRealtimeAgent(
        backend_client=_FailingBackend(),  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number="+15551234567",
    )

    seen_instructions: list[str] = []
    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            seen_instructions.append(str(instructions or ""))

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

    assert len(seen_instructions) == 1
    assert "Hello" in seen_instructions[0]
    assert "Sarah" in seen_instructions[0]


@pytest.mark.asyncio
async def test_openai_realtime_agent_on_enter_greets_without_caller_id() -> None:
    backend = _Backend({"customer": {"id": None, "first_name": None}})
    agent = OpenAIRealtimeAgent(
        backend_client=backend,  # type: ignore[arg-type]
        call_id_fallback="room-test",
        sip_phone_number=None,
    )

    seen_instructions: list[str] = []
    async with AgentSession() as session:
        def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
            _ = kwargs
            seen_instructions.append(str(instructions or ""))

        session.generate_reply = fake_generate_reply  # type: ignore[assignment]

        await session.start(agent)
        await agent.on_enter()

    assert backend.calls == []
    assert seen_instructions == []
