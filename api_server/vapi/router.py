"""Vapi tool-call HTTP endpoint.

This is the entrypoint Vapi calls for "tool-calls".

For MVP (TDD Step 1), this endpoint only returns the correct Vapi response format.
Tool dispatching is added in later TDD steps.
"""

from __future__ import annotations

import json
import logging
import os
import time

from fastapi import APIRouter, Depends, Request

from api_server.server.dependencies import DatabaseClient, get_database_client
from api_server.vapi.dispatcher import dispatch_tool_call
from api_server.vapi.session_store import SessionStore
from api_server.vapi.assistant_request import build_assistant_request_response
from api_server.vapi.tool_call_parsing import get_tool_call_id, get_tool_name


vapi_router = APIRouter()

logger = logging.getLogger(__name__)

HANDOFF_TOOL_DESTINATIONS = {
    "handoff_to_ServiceCollection": "7eb8818b-16ff-4236-b4d1-9eca3c7d9972",
    "handoff_to_CustomerIntake": "553a6ddd-6505-400b-9169-c6a0cf894dec",
    "handoff_to_Booking": "53748b6f-2afe-4147-9ff7-e189acec4223",
}

# Reason: singleton store shared across all requests (MVP single-instance)
_session_store = SessionStore()

# Reason: expose session_store for tests (similar to existing squad tool server tests)
session_store = _session_store


@vapi_router.post("/tools")
async def handle_vapi_tool_calls(
    request: Request,
    database_client: DatabaseClient = Depends(get_database_client),
) -> dict:
    """Handle Vapi tool-call requests and return Vapi results format."""
    log_timing = os.environ.get("VAPI_TOOLS_LOG_TIMING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    request_start = time.perf_counter()

    request_payload = await request.json()
    message_payload = request_payload.get("message", {})
    tool_call_list = message_payload.get("toolCallList") or message_payload.get("toolCalls") or []

    results: list[dict[str, str]] = []
    destination: dict[str, str] | None = None
    for tool_call in tool_call_list:
        tool_call_id = get_tool_call_id(tool_call)
        tool_name = get_tool_name(tool_call)
        tool_start = time.perf_counter()
        handoff_destination = HANDOFF_TOOL_DESTINATIONS.get(tool_name)
        if handoff_destination:
            results.append(
                {
                    "toolCallId": tool_call_id,
                    "result": "Transferring",
                }
            )
            # Reason: honor the most recent handoff tool call when multiple are present.
            destination = {"type": "assistant", "assistantId": handoff_destination}
            continue

        tool_result = await dispatch_tool_call(
            tool_call=tool_call,
            message_payload=message_payload,
            session_store=_session_store,
            database_client=database_client,
        )
        if log_timing:
            call_id = (message_payload.get("call") or {}).get("id")
            tool_ms = (time.perf_counter() - tool_start) * 1000
            logger.info(
                "vapi_tool_timing call_id=%s tool=%s toolCallId=%s ms=%.1f",
                call_id,
                tool_name,
                tool_call_id,
                tool_ms,
            )

        results.append(
            {
                "toolCallId": tool_call_id,
                "result": json.dumps(tool_result),
            }
        )

    response_payload: dict[str, object] = {"results": results}
    if destination is not None:
        response_payload["destination"] = destination

    if log_timing:
        call_id = (message_payload.get("call") or {}).get("id")
        request_ms = (time.perf_counter() - request_start) * 1000
        logger.info(
            "vapi_tools_request_timing call_id=%s toolCalls=%d ms=%.1f",
            call_id,
            len(tool_call_list),
            request_ms,
        )

    return response_payload


@vapi_router.post("/assistant-request")
async def handle_vapi_assistant_request(
    request: Request,
    database_client: DatabaseClient = Depends(get_database_client),
) -> dict:
    """Handle Vapi assistant-request webhook and return squad selection payload."""
    request_payload = await request.json()
    message_payload = request_payload.get("message")
    if not isinstance(message_payload, dict):
        message_payload = {}

    return build_assistant_request_response(
        message_payload=message_payload,
        database_client=database_client,
    )
