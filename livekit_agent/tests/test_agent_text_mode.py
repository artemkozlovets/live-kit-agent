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

from livekit_agent.agent import VapiAdapterAgent, _THEN_ACTION_FALLBACK_PROMPT  # noqa: E402
from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: E402


@pytest.mark.asyncio
async def test_agent_preflight_then_business_turn_text_mode() -> None:
    calls: list[str] = []
    assistant_messages: list[str] = []

    async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_call = payload["message"]["toolCallList"][0]
        tool_call_id = tool_call["id"]
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        calls.append(tool_name)

        if tool_name == "validate_phone":
            phone = tool_args.get("phone_number")
            call_phone = payload["message"]["call"]["customer"]["number"]
            assert call_phone == phone  # first send is unnormalized, right after confirmation
            formatted = phone
            if isinstance(phone, str) and phone.strip() and not phone.startswith("+"):
                formatted = f"+1{phone}"
            result_obj = {"valid": True, "formatted": formatted}
        elif tool_name == "check_customer":
            assert payload["message"]["call"]["customer"]["number"] == "+15551234567"
            result_obj = {"found": True, "next_action": "Proceed. Call handoff_to_ServiceCollection."}
        elif tool_name == "get_case_status":
            result_obj = {
                "response_mode": "speak_first",
                "immediate_message": "Okay — what's the VIN or unit number?",
                "then_action": "Call get_session_summary.",
            }
        elif tool_name == "get_session_summary":
            result_obj = {"ok": True}
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

        # Turn 1: provide callback number; should validate + check customer before allowing get_case_status.
        await agent.on_user_turn_completed(ChatContext(), _Msg("5551234567"))
        assert "validate_phone" in calls
        assert "check_customer" in calls
        assert "get_case_status" not in calls

        # Turn 2: agent transitions to main flow with a deterministic prompt.
        await agent.on_user_turn_completed(ChatContext(), _Msg("Hi"))
        start = time.monotonic()
        while "Thanks — how can I help today?" not in assistant_messages and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)
        assert "Thanks — how can I help today?" in assistant_messages

        # Turn 3: main flow calls get_case_status and speaks immediate_message.
        await agent.on_user_turn_completed(ChatContext(), _Msg("I need roadside assistance"))
        assert "get_case_status" in calls
        assert "get_session_summary" in calls
        start = time.monotonic()
        while not any("VIN" in msg for msg in assistant_messages) and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)
        assert any("VIN" in msg for msg in assistant_messages)


class _FailingToolLLM:
    class _Stream:
        async def __aenter__(self) -> None:
            raise RuntimeError("tool llm failure")

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def __aiter__(self) -> "_FailingToolLLM._Stream":
            return self

        async def __anext__(self) -> Any:
            raise StopAsyncIteration

    def chat(self, **kwargs: Any) -> "_FailingToolLLM._Stream":
        return self._Stream()


@pytest.mark.asyncio
async def test_tool_llm_failure_falls_back_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_CALLBACK_PREFLIGHT", "1")

    assistant_messages: list[str] = []

    async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_call = payload["message"]["toolCallList"][0]
        tool_call_id = tool_call["id"]
        tool_name = tool_call["function"]["name"]

        if tool_name == "get_case_status":
            result_obj = {
                "response_mode": "tool_first",
                "immediate_message": None,
                "then_action": "Collect vehicle info and service complaint.",
            }
        else:
            result_obj = {"ok": True}

        return {"results": [{"toolCallId": tool_call_id, "result": json.dumps(result_obj)}]}

    backend = BackendToolsClient(tools_url="https://example.test/vapi/tools", post_json=post_json)

    agent = VapiAdapterAgent(
        backend_client=backend,
        call_id_fallback="room-test",
        tool_llm=_FailingToolLLM(),
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

        # Turn 1: skip preflight and enter main flow.
        await agent.on_user_turn_completed(ChatContext(), _Msg("hello"))

        # Turn 2: triggers get_case_status and then_action parsing.
        await agent.on_user_turn_completed(ChatContext(), _Msg("I need help with my car"))

        start = time.monotonic()
        while _THEN_ACTION_FALLBACK_PROMPT not in assistant_messages and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

        assert _THEN_ACTION_FALLBACK_PROMPT in assistant_messages
