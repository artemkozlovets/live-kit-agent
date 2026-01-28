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

from livekit_agent.agent import VapiAdapterAgent  # noqa: E402
from livekit_agent.backend_tools_client import BackendToolsClient  # noqa: E402


@pytest.mark.asyncio
async def test_agent_slot_filling_v2_booking_not_confirmed_prompts_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_SLOT_FILLING", "1")
    monkeypatch.setenv("AGENT_FAST_INTAKE", "1")

    calls: list[str] = []
    assistant_messages: list[str] = []
    store_attempts = 0

    async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        nonlocal store_attempts

        assert url.endswith("/tools")
        assert headers is not None
        assert headers.get("X-TOOLS-TOKEN") == "test-secret"

        tool_call = payload["tool_calls"][0]
        tool_call_id = tool_call["id"]
        tool_name = tool_call["name"]

        calls.append(tool_name)

        if tool_name == "get_case_status":
            result_obj = {
                "current_phase": "booking",
                "missing_fields": ["confirmation"],
                "customer": {"id": "CUST-1", "first_name": "John", "last_name": "Johnson", "phone": "+13053179840", "email": None, "company": None},
                "service": {"id": None, "vin": "VIN123", "unit_number": None, "unit_nickname": None, "location": "6th Street", "location_is_safe": None, "is_mobile": None, "complaint": "flat tire"},
                "customer_known_data": {"first_name": "John", "last_name": "Johnson", "phone_number": "+13053179840"},
            }
            return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": result_obj}]}

        if tool_name == "get_session_summary":
            result_obj = {
                "service_count": 1,
                "services": [
                    {"vin_number": "VIN123", "service_location": "6th Street", "service_complaint": "flat tire", "vehicle_id_type": "vin"}
                ],
                "services_confirmed": False,
            }
            return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": result_obj}]}

        if tool_name == "confirm_services":
            return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": {"confirmed": True}}]}

        if tool_name == "store_service_order":
            store_attempts += 1
            if store_attempts == 1:
                return {
                    "results": [
                        {
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "ok": False,
                            "error": {"code": "booking_not_confirmed", "message": "User must confirm."},
                        }
                    ]
                }
            return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": {"success": True, "order_ids": ["ORDER-1"]}}]}

        return {"results": [{"tool_call_id": tool_call_id, "name": tool_name, "ok": True, "result": {"ok": True}}]}

    backend = BackendToolsClient(
        tools_url="https://example.test/tools",
        post_json=post_json,
        tools_token="test-secret",
    )

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

        # Turn 1: agent asks for confirmation.
        await agent.on_user_turn_completed(ChatContext(), _Msg("info dump"))
        start = time.monotonic()
        while not any("Just to confirm" in msg for msg in assistant_messages) and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

        # Turn 2: user says yes, but backend rejects booking_not_confirmed.
        await agent.on_user_turn_completed(ChatContext(), _Msg("Yes"))

        start = time.monotonic()
        while not any("Just to confirm" in msg for msg in assistant_messages[1:]) and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

    assert "store_service_order" in calls
    assert store_attempts == 1
    assert any("Just to confirm" in msg for msg in assistant_messages[1:])
