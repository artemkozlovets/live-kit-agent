"""Helpers for parsing Vapi tool-call payloads.

Vapi can send tool calls in a few slightly different shapes depending on the
model/provider integration. This module keeps that parsing logic in one place so
our router/dispatcher/handlers stay simple.
"""

from __future__ import annotations

import json
from typing import Any


def _unwrap_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Return the actual tool call payload.

    Some Vapi message payloads wrap the real tool call under `toolCall`.
    """
    nested_tool_call = tool_call.get("toolCall")
    return nested_tool_call if isinstance(nested_tool_call, dict) else tool_call


def get_tool_call_id(tool_call: dict[str, Any]) -> str:
    tool_call_payload = _unwrap_tool_call(tool_call)
    tool_call_id = tool_call_payload.get("id")
    return str(tool_call_id) if tool_call_id else ""


def get_tool_name(tool_call: dict[str, Any]) -> str:
    tool_call_payload = _unwrap_tool_call(tool_call)

    # OpenAI-style: {"function": {"name": "...", "arguments": ...}}
    function_payload = tool_call_payload.get("function")
    if isinstance(function_payload, dict):
        tool_name = function_payload.get("name")
        return str(tool_name) if tool_name else ""

    # Vapi style: {"name": "...", "arguments": ...}
    tool_name = tool_call_payload.get("name")
    return str(tool_name) if tool_name else ""


def parse_tool_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Parse tool arguments, supporting dict or JSON-string inputs."""
    tool_call_payload = _unwrap_tool_call(tool_call)

    raw_arguments: Any = None
    function_payload = tool_call_payload.get("function")
    if isinstance(function_payload, dict):
        raw_arguments = function_payload.get("arguments")
    else:
        raw_arguments = tool_call_payload.get("arguments", tool_call_payload.get("parameters"))

    # Reason: Vapi may send arguments as a JSON string or as a dict.
    if isinstance(raw_arguments, str):
        if not raw_arguments:
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    if isinstance(raw_arguments, dict):
        return raw_arguments

    return {}


def get_call_id(message_payload: dict[str, Any]) -> str:
    call_payload = message_payload.get("call", {}) or {}
    call_id = call_payload.get("id")
    return str(call_id) if call_id else ""


def get_extracted_variables(message_payload: dict[str, Any]) -> dict[str, Any]:
    assistant_payload = message_payload.get("assistant", {}) or {}
    extracted_variables = assistant_payload.get("extractedVariables", {}) or {}
    return extracted_variables if isinstance(extracted_variables, dict) else {}

