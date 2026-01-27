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

from livekit_agent.agent import VapiAdapterAgent  # noqa: E402
from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: E402


@pytest.mark.asyncio
async def test_agent_fast_intake_greets_and_calls_get_case_status_on_first_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expected use: greet once, then process the user's first message immediately."""
    monkeypatch.setenv("AGENT_FAST_INTAKE", "1")
    monkeypatch.setenv("AGENT_GREETING", "Hello, this is Sarah from AFS, how can I help?")

    calls: list[str] = []
    assistant_messages: list[str] = []

    async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_call = payload["message"]["toolCallList"][0]
        tool_call_id = tool_call["id"]
        tool_name = tool_call["function"]["name"]
        calls.append(tool_name)

        if tool_name == "get_case_status":
            result_obj = {
                "response_mode": "speak_first",
                "immediate_message": "What vehicle do you need service for?",
                "then_action": "",
            }
        else:
            result_obj = {"ok": True}

        return {"results": [{"toolCallId": tool_call_id, "result": json.dumps(result_obj)}]}

    backend = BackendToolsClient(tools_url="https://example.test/vapi/tools", post_json=post_json)

    agent = VapiAdapterAgent(
        backend_client=backend,
        call_id_fallback="room-test",
        tool_llm=None,
        sip_phone_number=None,
    )

    class _Msg:
        def __init__(self, text: str) -> None:
            self.text_content = text

    async with AgentSession() as session:
        @session.on("conversation_item_added")
        def on_item(ev: Any) -> None:
            item = getattr(ev, "item", None)
            if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
                assistant_messages.append((getattr(item, "text_content", None) or "").strip())

        await session.start(agent)

        start = time.monotonic()
        while (
            "Hello, this is Sarah from AFS, how can I help?" not in assistant_messages
            and time.monotonic() - start < 1.0
        ):
            await asyncio.sleep(0.01)

        assert "Hello, this is Sarah from AFS, how can I help?" in assistant_messages

        # First user turn: should immediately call get_case_status (no "Thanks..." extra gate).
        await agent.on_user_turn_completed(ChatContext(), _Msg("I have a flat tire."))
        assert "get_case_status" in calls
        assert "Thanks — how can I help today?" not in assistant_messages

        start = time.monotonic()
        while (
            "What vehicle do you need service for?" not in assistant_messages
            and time.monotonic() - start < 1.0
        ):
            await asyncio.sleep(0.01)

        assert "What vehicle do you need service for?" in assistant_messages

