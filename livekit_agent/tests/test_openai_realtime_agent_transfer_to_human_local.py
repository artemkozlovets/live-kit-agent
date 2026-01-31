from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


class _Backend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(str(kwargs.get("tool_name")))
        return {"ok": True}


@pytest.mark.asyncio
async def test_transfer_to_human_is_local_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _Backend()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    async def fake_transfer() -> dict[str, Any]:
        return {"ok": True, "transfer_to": "tel:+15551234567"}

    monkeypatch.setattr(agent, "_transfer_to_human", fake_transfer)

    result = await agent.forward_tool(tool_name="transfer_to_human", tool_arguments={})

    assert result == {"ok": True, "transfer_to": "tel:+15551234567"}
    assert backend.calls == []

