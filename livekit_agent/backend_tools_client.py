from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from livekit_agent.vapi_payload import build_vapi_tool_call_request

logger = logging.getLogger("livekit-agent-vapi-adapter.backend-tools")


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _mask_phone_like(value: str) -> str:
    if _truthy_env("LOG_PII"):
        return value

    stripped = value.strip()
    if stripped.startswith("+") and stripped[1:].isdigit() and len(stripped) >= 8:
        return f"+{stripped[1:3]}{'*' * (len(stripped) - 6)}{stripped[-4:]}"
    if stripped.isdigit() and len(stripped) >= 8:
        return f"{'*' * (len(stripped) - 4)}{stripped[-4:]}"
    return value


def _safe_keys(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted([str(key) for key in value.keys()])


class BackendToolsClientError(Exception):
    pass


class BackendToolsTransportError(BackendToolsClientError):
    pass


class BackendToolsResponseError(BackendToolsClientError):
    pass


class ToolResultMissingError(BackendToolsClientError):
    pass


class ToolResultParseError(BackendToolsClientError):
    pass


PostJson = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BackendToolsClient:
    tools_url: str
    post_json: PostJson | None = None
    timeout_s: float = 30.0

    async def call_tool(
        self,
        *,
        call_id: str,
        sip_phone_number: str | None,
        confirmed_callback_number: str | None,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        masked_call_id = _mask_phone_like(call_id)

        logger.debug(
            "calling backend tool",
            extra={
                "call_id": masked_call_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "argument_keys": sorted(tool_arguments.keys()),
            },
        )

        payload = build_vapi_tool_call_request(
            call_id=call_id,
            sip_phone_number=sip_phone_number,
            confirmed_callback_number=confirmed_callback_number,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

        post_json = self.post_json or self._default_post_json
        try:
            response = await post_json(self.tools_url, payload)
        except TimeoutError as exc:
            logger.warning(
                "backend tools request timed out",
                extra={
                    "call_id": masked_call_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                },
            )
            raise BackendToolsTransportError("Backend tools request timed out") from exc
        except Exception as exc:
            logger.warning(
                "backend tools request failed",
                extra={
                    "call_id": masked_call_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                },
                exc_info=exc,
            )
            raise BackendToolsTransportError("Backend tools request failed") from exc

        results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(results, list):
            raise BackendToolsResponseError("Backend response missing 'results' list")

        matched_result: dict[str, Any] | None = None
        for result in results:
            if isinstance(result, dict) and result.get("toolCallId") == tool_call_id:
                matched_result = result
                break

        if matched_result is None:
            raise ToolResultMissingError(f"Tool result for toolCallId={tool_call_id} not found")

        raw_result = matched_result.get("result")
        if isinstance(raw_result, dict):
            logger.debug(
                "backend tool result received",
                extra={
                    "call_id": masked_call_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "result_keys": _safe_keys(raw_result),
                },
            )
            return raw_result
        if not isinstance(raw_result, str):
            raise ToolResultParseError("Tool result is not a JSON string")

        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise ToolResultParseError("Tool result is not valid JSON") from exc

        if not isinstance(parsed, dict):
            raise ToolResultParseError("Tool result JSON must be an object")

        logger.debug(
            "backend tool result received",
            extra={
                "call_id": masked_call_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "result_keys": _safe_keys(parsed),
            },
        )
        return parsed

    async def _default_post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url=url,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    status = getattr(response, "status", None)
                    body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
                raise BackendToolsResponseError(
                    f"Backend responded with HTTP {exc.code}: {body}"
                ) from exc
            except urllib.error.URLError as exc:
                raise BackendToolsTransportError("Backend connection failed") from exc

            if status is None or status < 200 or status >= 300:
                raise BackendToolsResponseError(f"Backend responded with HTTP {status}: {body}")

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise BackendToolsResponseError("Backend returned invalid JSON") from exc

            if not isinstance(parsed, dict):
                raise BackendToolsResponseError("Backend returned non-object JSON")

            return parsed

        return await asyncio.to_thread(_send)

