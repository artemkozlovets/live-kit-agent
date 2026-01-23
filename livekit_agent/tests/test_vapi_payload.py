import json

import pytest

from livekit_agent.vapi_payload import (
    build_vapi_tool_call_request,
    build_vapi_tool_calls_request,
)


def test_build_vapi_tool_call_request_happy_path() -> None:
    payload = build_vapi_tool_call_request(
        call_id="room-123",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_call_id="tool-call-abc",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+15551230000"},
    )

    message = payload["message"]
    assert message["type"] == "tool-calls"
    assert message["call"]["id"] == "room-123"
    assert message["customer"]["number"] == "+15551230000"
    assert message["call"]["customer"]["number"] == "+15551230000"

    tool_call = message["toolCallList"][0]
    assert tool_call["id"] == "tool-call-abc"
    assert tool_call["function"]["name"] == "validate_phone"
    assert isinstance(tool_call["function"]["arguments"], str)

    parsed = json.loads(tool_call["function"]["arguments"])
    assert parsed == {"phone_number": "+15551230000"}


def test_build_vapi_tool_call_request_no_sip_phone_number() -> None:
    payload = build_vapi_tool_call_request(
        call_id="room-456",
        sip_phone_number=None,
        confirmed_callback_number=None,
        tool_call_id="tool-call-1",
        tool_name="get_case_status",
        tool_arguments={"last_user_message": "Hello"},
    )

    message = payload["message"]
    assert message["customer"]["number"] is None
    assert "customer" not in message["call"]


def test_build_vapi_tool_call_request_requires_call_id() -> None:
    with pytest.raises(ValueError):
        build_vapi_tool_call_request(
            call_id="",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )


def test_build_vapi_tool_calls_request_multiple_tool_calls() -> None:
    payload = build_vapi_tool_calls_request(
        call_id="room-123",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_calls=[
            {
                "id": "tool-call-1",
                "name": "check_customer",
                "arguments": {"phone_number": "+15551230000"},
            },
            {
                "id": "tool-call-2",
                "name": "get_case_status",
                "arguments": {"last_user_message": "Hi"},
            },
        ],
    )

    tool_calls = payload["message"]["toolCallList"]
    assert [tc["id"] for tc in tool_calls] == ["tool-call-1", "tool-call-2"]
    assert [tc["function"]["name"] for tc in tool_calls] == ["check_customer", "get_case_status"]
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"phone_number": "+15551230000"}
    assert json.loads(tool_calls[1]["function"]["arguments"]) == {"last_user_message": "Hi"}

