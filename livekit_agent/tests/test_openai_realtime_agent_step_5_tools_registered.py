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
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {
                "tool_name": kwargs.get("tool_name"),
                "tool_arguments": kwargs.get("tool_arguments"),
            }
        )
        return {"ok": True}


@pytest.mark.asyncio
async def test_openai_realtime_agent_registers_backend_tools_and_forwards() -> None:
    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    tool_names = {getattr(getattr(tool, "info", None), "name", None) for tool in agent.tools}
    assert "validate_phone" in tool_names
    assert "check_customer" in tool_names
    assert "transfer_to_human" in tool_names

    # Reason: get_case_status is a mandatory pre-turn hook, not an LLM tool.
    assert "get_case_status" not in tool_names

    assert not any(isinstance(name, str) and name.startswith("handoff_to_") for name in tool_names)

    validate_tool = next(tool for tool in agent.tools if getattr(getattr(tool, "info", None), "name", None) == "validate_phone")

    async with AgentSession() as session:
        await session.start(agent)
        await validate_tool({"phone_number": "123"}, None)

    assert backend.calls == [{"tool_name": "validate_phone", "tool_arguments": {"phone_number": "123"}}]
