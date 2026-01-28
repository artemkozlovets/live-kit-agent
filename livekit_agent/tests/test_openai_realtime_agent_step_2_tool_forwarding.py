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

from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: E402
from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402


@pytest.mark.asyncio
async def test_openai_realtime_agent_tool_forwarding_preserves_parent_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("TOOLS_TOKEN", "test-secret")

    async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        assert url.endswith("/tools")
        assert headers is not None
        assert headers.get("X-TOOLS-TOKEN") == "test-secret"

        assert payload["customer"]["number"] == "+15551230000"
        assert payload["call"]["customer"]["number"] == "+15551230001"

        assert payload["assistant"]["variable_values"] == {"customerId": "CUST-123", "isKnownCustomer": "true"}

        tool_call = payload["tool_calls"][0]
        assert tool_call["name"] == "validate_phone"
        assert isinstance(tool_call["arguments"], dict)

        return {
            "results": [
                {"tool_call_id": tool_call["id"], "name": "validate_phone", "ok": True, "result": {"ok": True}}
            ]
        }

    backend = BackendToolsClient(
        tools_url="https://backend.test/tools",
        post_json=post_json,
        tools_token="test-secret",
    )

    agent = OpenAIRealtimeAgent(
        backend_client=backend,
        call_id_fallback="room-test",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230001",
        assistant_variable_values={"customerId": "CUST-123", "isKnownCustomer": "true"},
    )

    async with AgentSession() as session:
        await session.start(agent)

        # Act
        result = await agent.forward_tool(tool_name="validate_phone", tool_arguments={"phone_number": "123"})

    # Assert
    assert result == {"ok": True}
