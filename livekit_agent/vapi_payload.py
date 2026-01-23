from __future__ import annotations

import json
from typing import Any


def build_vapi_tool_calls_request(
    *,
    call_id: str,
    sip_phone_number: str | None,
    confirmed_callback_number: str | None,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("call_id is required")

    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError("tool_calls must be a non-empty list")

    tool_call_list: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            raise ValueError("tool_calls must contain dict entries")

        tool_call_id = tool_call.get("id")
        tool_name = tool_call.get("name")
        tool_arguments = tool_call.get("arguments")

        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise ValueError("tool call id is required")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool name is required")
        if not isinstance(tool_arguments, dict):
            raise ValueError("tool arguments must be a dict")

        tool_call_list.append(
            {
                "id": tool_call_id,
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_arguments),
                },
            }
        )

    message_call: dict[str, Any] = {"id": call_id}
    if isinstance(confirmed_callback_number, str) and confirmed_callback_number.strip():
        message_call["customer"] = {"number": confirmed_callback_number}

    return {
        "message": {
            "type": "tool-calls",
            "call": message_call,
            "customer": {"number": sip_phone_number if sip_phone_number else None},
            "toolCallList": tool_call_list,
            "assistant": {"extractedVariables": {}},
        }
    }


def build_vapi_tool_call_request(
    *,
    call_id: str,
    sip_phone_number: str | None,
    confirmed_callback_number: str | None,
    tool_call_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
) -> dict[str, Any]:
    return build_vapi_tool_calls_request(
        call_id=call_id,
        sip_phone_number=sip_phone_number,
        confirmed_callback_number=confirmed_callback_number,
        tool_calls=[
            {"id": tool_call_id, "name": tool_name, "arguments": tool_arguments},
        ],
    )

