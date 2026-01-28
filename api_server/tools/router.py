from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api_server.server.dependencies import DatabaseClient, get_database_client
from api_server.vapi.dispatcher import dispatch_tool_call
from api_server.vapi.router import session_store
from api_server.vapi.tool_call_parsing import get_call_id, get_tool_call_id, get_tool_name

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_tools_token(request: Request) -> None:
    expected = os.getenv("TOOLS_TOKEN", "").strip()
    if not expected:
        # Reason: This endpoint must never be publicly callable; missing token is a deploy misconfig.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TOOLS_TOKEN not configured",
        )

    provided = request.headers.get("X-TOOLS-TOKEN", "").strip()
    if not provided or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _local_observability_dir() -> str | None:
    raw = os.getenv("LOCAL_OBSERVABILITY_DIR", "").strip()
    return raw or None


def _append_local_jsonl(filename: str, payload: dict[str, object]) -> None:
    local_dir = _local_observability_dir()
    if not local_dir:
        return

    try:
        os.makedirs(local_dir, exist_ok=True)
        path = os.path.join(local_dir, filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str))
            f.write("\n")
    except Exception:
        # Reason: Local observability is best-effort and must never break the production request path.
        logger.exception("Failed to write local observability artifact")


def _build_message_payload_v1_compat(request_payload: dict[str, Any]) -> dict[str, Any]:
    call_payload = request_payload.get("call")
    if not isinstance(call_payload, dict):
        call_payload = {}

    message_payload: dict[str, Any] = {
        "type": "tool-calls",
        # Reason: Many existing handlers key off message_payload["call"].
        "call": dict(call_payload),
        # Reason: Preserve v2 parent structures for downstream usage.
        "customer": request_payload.get("customer"),
        "assistant": request_payload.get("assistant"),
        # Reason: Explicitly tag this as the provider-agnostic v2 tools endpoint so
        # handlers can enforce "realtime mode" constraints (no Gemini calls).
        "_tools_api_version": 2,
    }

    assistant_payload = request_payload.get("assistant")
    if isinstance(assistant_payload, dict):
        variable_values = assistant_payload.get("variable_values")
        if isinstance(variable_values, dict):
            # Reason: Keep public v2 contract provider-agnostic, but map into the existing
            # override path internally (used by get_case_status known-customer overrides).
            message_payload["assistantOverrides"] = {"variableValues": variable_values}

    return message_payload


def _validate_tools_v2_request(request_payload: object) -> dict[str, Any]:
    if not isinstance(request_payload, dict):
        raise _bad_request("Invalid JSON payload")

    call_payload = request_payload.get("call")
    if not isinstance(call_payload, dict):
        raise _bad_request("Invalid call payload")

    call_id = call_payload.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise _bad_request("Missing call.id")

    tool_calls = request_payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise _bad_request("tool_calls must be a list")

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            raise _bad_request("tool_calls entries must be objects")
        if not isinstance(tool_call.get("id"), str) or not tool_call["id"].strip():
            raise _bad_request("tool_calls[].id must be a non-empty string")
        if not isinstance(tool_call.get("name"), str) or not tool_call["name"].strip():
            raise _bad_request("tool_calls[].name must be a non-empty string")
        arguments = tool_call.get("arguments")
        if not isinstance(arguments, dict):
            raise _bad_request("tool_calls[].arguments must be an object")

    return request_payload


def _result_ok_from_handler(tool_name: str, tool_result: dict[str, Any]) -> bool:
    # Reason: v2 `ok=false` is reserved for tool execution failures / policy rejections,
    # not negative outcomes (e.g., validate_phone valid=false is still a valid response).
    if tool_name in {"confirm_services"}:
        confirmed = tool_result.get("confirmed")
        if isinstance(confirmed, bool) and confirmed is False:
            return False
    if tool_name in {"store_service_order"}:
        success = tool_result.get("success")
        if isinstance(success, bool) and success is False:
            return False
    return True


@router.post("/tools")
async def handle_tools_v2(
    request: Request,
    database_client: DatabaseClient = Depends(get_database_client),
) -> dict[str, object]:
    request_start = time.perf_counter()
    _require_tools_token(request)

    try:
        raw_payload: object = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON body for /tools", exc_info=exc)
        raise _bad_request("Invalid JSON payload") from exc

    request_payload = _validate_tools_v2_request(raw_payload)
    tool_calls = request_payload.get("tool_calls", [])
    message_payload = _build_message_payload_v1_compat(request_payload)
    call_id = get_call_id(message_payload)

    results: list[dict[str, object]] = []
    trace_tool_calls: list[dict[str, object]] = []
    for tool_call in tool_calls:
        tool_call_id = get_tool_call_id(tool_call)
        tool_name = get_tool_name(tool_call)

        if tool_name == "store_service_order":
            # Reason: Booking must never proceed without explicit user confirmation
            # (confirmed via confirm_services).
            session = session_store.get(call_id) if call_id else {}
            if session.get("services_confirmed") is not True:
                results.append(
                    {
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "ok": False,
                        "error": {
                            "code": "booking_not_confirmed",
                            "message": "User has not explicitly confirmed the booking.",
                        },
                    }
                )
                trace_tool_calls.append(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "argument_keys": sorted([str(k) for k in (tool_call.get("arguments") or {}).keys()]),
                        "result_keys": [],
                    }
                )
                continue

        tool_result = await dispatch_tool_call(
            tool_call=tool_call,
            message_payload=message_payload,
            session_store=session_store,
            database_client=database_client,
        )

        if isinstance(tool_result, dict) and tool_result.get("error") == f"Unknown tool: {tool_name}":
            results.append(
                {
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "ok": False,
                    "error": {
                        "code": "unknown_tool",
                        "message": f"Unknown tool: {tool_name}",
                    },
                }
            )
            trace_tool_calls.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "argument_keys": sorted([str(k) for k in (tool_call.get("arguments") or {}).keys()]),
                    "result_keys": [],
                }
            )
            continue

        if not isinstance(tool_result, dict):
            raise RuntimeError(f"Tool handler returned non-object for tool={tool_name} call_id={call_id}")

        ok = _result_ok_from_handler(tool_name, tool_result)
        if ok:
            results.append(
                {
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "ok": True,
                    "result": tool_result,
                }
            )
            trace_tool_calls.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "argument_keys": sorted([str(k) for k in (tool_call.get("arguments") or {}).keys()]),
                    "result_keys": sorted([str(k) for k in tool_result.keys()]),
                }
            )
            continue

        error_message = tool_result.get("error")
        if not isinstance(error_message, str) or not error_message.strip():
            error_message = "Tool execution failed"

        results.append(
            {
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "ok": False,
                "error": {
                    "code": "tool_rejected",
                    "message": error_message,
                },
            }
        )
        trace_tool_calls.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "argument_keys": sorted([str(k) for k in (tool_call.get("arguments") or {}).keys()]),
                "result_keys": sorted([str(k) for k in tool_result.keys()]) if isinstance(tool_result, dict) else [],
            }
        )

    request_ms = (time.perf_counter() - request_start) * 1000
    _append_local_jsonl(
        "backend.tools.jsonl",
        {
            "ts_unix_s": time.time(),
            "call_id": call_id,
            "elapsed_ms": round(request_ms, 3),
            "tool_calls": trace_tool_calls,
        },
    )

    return {"results": results}
