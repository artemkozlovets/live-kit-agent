from __future__ import annotations

from typing import Any


def build_tools_v2_request(
    *,
    call_id: str,
    customer_number_raw: str | None,
    call_customer_number_confirmed: str | None,
    assistant_variable_values: dict[str, str] | None,
    tool_calls: list[dict[str, object]],
) -> dict[str, Any]:
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("call_id is required")

    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError("tool_calls must be a non-empty list")

    normalized_tool_calls: list[dict[str, Any]] = []
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

        normalized_tool_calls.append(
            {
                "id": tool_call_id,
                "name": tool_name,
                "arguments": dict(tool_arguments),
            }
        )

    call_payload: dict[str, Any] = {"id": call_id}
    if isinstance(call_customer_number_confirmed, str) and call_customer_number_confirmed.strip():
        call_payload["customer"] = {"number": call_customer_number_confirmed.strip()}

    payload: dict[str, Any] = {
        "call": call_payload,
        "tool_calls": normalized_tool_calls,
    }

    if isinstance(customer_number_raw, str) and customer_number_raw.strip():
        payload["customer"] = {"number": customer_number_raw.strip()}

    if isinstance(assistant_variable_values, dict) and assistant_variable_values:
        payload["assistant"] = {"variable_values": dict(assistant_variable_values)}

    return payload

