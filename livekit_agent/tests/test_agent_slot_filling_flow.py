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
async def test_agent_slot_filling_info_dump_to_booking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_SLOT_FILLING", "1")
    monkeypatch.setenv("AGENT_FAST_INTAKE", "1")
    monkeypatch.setenv("AGENT_GREETING", "Hello, this is Sarah from AFS, how can I help?")

    calls: list[str] = []
    assistant_messages: list[str] = []

    async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_call = payload["message"]["toolCallList"][0]
        tool_call_id = tool_call["id"]
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        calls.append(tool_name)

        if tool_name == "get_case_status":
            result_obj = {
                "current_phase": "service_collection",
                "missing_fields": [],
                "customer": {
                    "id": None,
                    "first_name": "John",
                    "last_name": "Johnson",
                    "phone": "3053179840",
                    "email": None,
                    "company": "AFS",
                },
                "service": {
                    "id": None,
                    "vin": "VIN123",
                    "unit_number": None,
                    "unit_nickname": "Big Pete",
                    "location": "6th Street",
                    "location_is_safe": None,
                    "is_mobile": None,
                    "complaint": "flat tire",
                },
                "customer_known_data": {
                    "first_name": "John",
                    "last_name": "Johnson",
                    "company_name": "AFS",
                    "email_address": "john@example.com",
                    "phone_number": "3053179840",
                    "customer_position": None,
                    "marketing_source": None,
                    "streetAddress": "123 Main St",
                    "city": "Dallas",
                    "state": "TX",
                    "country": None,
                    "postalCode": "75201",
                },
            }
        elif tool_name == "validate_phone":
            assert tool_args["phone_number"] == "3053179840"
            result_obj = {"valid": True, "formatted": "+13053179840"}
        elif tool_name == "check_customer":
            assert tool_args["phone_number"] == "+13053179840"
            assert isinstance(tool_args.get("known_data"), dict)
            assert tool_args["known_data"]["streetAddress"] == "123 Main St"
            result_obj = {"found": False, "ready_to_register": True, "next_action_fields": []}
        elif tool_name == "register_new_customer":
            assert tool_args["phone_number"] == "+13053179840"
            assert tool_args["first_name"] == "John"
            assert tool_args["streetAddress"] == "123 Main St"
            result_obj = {"customer_id": "CUST-1"}
        elif tool_name == "get_session_summary":
            # First call occurs before add_service; second call after add_service.
            if "add_service" not in calls:
                result_obj = {"service_count": 0, "services": [], "services_confirmed": False}
            else:
                result_obj = {
                    "service_count": 1,
                    "services": [
                        {
                            "vin_number": "VIN123",
                            "unit_number": None,
                            "unit_nickname": "Big Pete",
                            "service_location": "6th Street",
                            "service_complaint": "flat tire",
                            "vehicle_id_type": "vin",
                        }
                    ],
                    "services_confirmed": False,
                }
        elif tool_name == "add_service":
            assert tool_args["vin_number"] == "VIN123"
            assert tool_args["service_location"] == "6th Street"
            assert tool_args["service_complaint"] == "flat tire"
            result_obj = {"added": True, "service_count": 1}
        elif tool_name == "store_service_order":
            result_obj = {"success": True, "order_ids": ["ORDER-1"]}
        elif tool_name == "send_confirmation_sms":
            result_obj = {"sent": False, "sms_status": "not_configured"}
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

        # Turn 1: info dump -> register + add service -> ask final confirmation.
        await agent.on_user_turn_completed(
            ChatContext(),
            _Msg(
                "My name is John Johnson. My phone number is three zero five three one seven nine eight four zero. "
                "My email is john@example.com. My address is 123 Main St, Dallas TX 75201. "
                "I have a flat tire at 6th Street, VIN VIN123."
            ),
        )

        start = time.monotonic()
        while not any("Just to confirm" in msg for msg in assistant_messages) and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

        assert "get_case_status" in calls
        assert "validate_phone" in calls
        assert "check_customer" in calls
        assert "register_new_customer" in calls
        assert "add_service" in calls
        assert "get_session_summary" in calls
        assert any("Just to confirm" in msg for msg in assistant_messages)

        # Turn 2: confirm -> store order -> send confirmation -> closing.
        await agent.on_user_turn_completed(ChatContext(), _Msg("Yes"))

        start = time.monotonic()
        while not any("You're all set" in msg for msg in assistant_messages) and time.monotonic() - start < 1.0:
            await asyncio.sleep(0.01)

        assert "store_service_order" in calls
        assert "send_confirmation_sms" in calls
        assert any("You're all set" in msg for msg in assistant_messages)

