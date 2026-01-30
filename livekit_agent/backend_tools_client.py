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

from livekit_agent.tools_v2_payload import build_tools_v2_request

logger = logging.getLogger("livekit-agent.backend-tools")


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


class BookingNotConfirmedError(BackendToolsClientError):
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
    tools_token: str | None = None

    async def call_tool(
        self,
        *,
        call_id: str,
        sip_phone_number: str | None,
        confirmed_callback_number: str | None,
        assistant_variable_values: dict[str, str] | None = None,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        masked_call_id = _mask_phone_like(call_id)
        voice_debug = _truthy_env("VOICE_DEBUG")

        if voice_debug:
            logger.info(
                "VOICE_DEBUG backend_tool_start",
                extra={
                    "call_id": masked_call_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "argument_keys": sorted(tool_arguments.keys()),
                },
            )

        logger.debug(
            "calling backend tool",
            extra={
                "call_id": masked_call_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "argument_keys": sorted(tool_arguments.keys()),
            },
        )

        tools_token = (self.tools_token or os.getenv("TOOLS_TOKEN", "")).strip()
        if not tools_token:
            raise BackendToolsClientError("TOOLS_TOKEN is required for /tools")

        headers: dict[str, str] = {"X-TOOLS-TOKEN": tools_token}
        payload = build_tools_v2_request(
            call_id=call_id,
            customer_number_raw=sip_phone_number,
            call_customer_number_confirmed=confirmed_callback_number,
            assistant_variable_values=assistant_variable_values,
            tool_calls=[
                {"id": tool_call_id, "name": tool_name, "arguments": tool_arguments},
            ],
        )

        post_json = self.post_json or self._default_post_json
        try:
            try:
                response = await post_json(self.tools_url, payload, headers=headers)  # type: ignore[misc]
            except TypeError:
                # Reason: Backwards-compatible DI for existing tests/mocks.
                response = await post_json(self.tools_url, payload)
        except TimeoutError as exc:
            if voice_debug:
                logger.info(
                    "VOICE_DEBUG backend_tool_timeout",
                    extra={
                        "call_id": masked_call_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
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
            if voice_debug:
                logger.info(
                    "VOICE_DEBUG backend_tool_error",
                    extra={
                        "call_id": masked_call_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "error_type": type(exc).__name__,
                    },
                )
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

        parsed = self._parse_tools_v2_result(
            results=results,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            masked_call_id=masked_call_id,
            started=started,
        )
        if voice_debug:
            logger.info(
                "VOICE_DEBUG backend_tool_ok",
                extra={
                    "call_id": masked_call_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "result_keys": _safe_keys(parsed),
                },
            )
        return parsed

    def _parse_tools_v2_result(
        self,
        *,
        results: list[object],
        tool_call_id: str,
        tool_name: str,
        masked_call_id: str,
        started: float,
    ) -> dict[str, Any]:
        matched_result: dict[str, Any] | None = None
        for result in results:
            if isinstance(result, dict) and result.get("tool_call_id") == tool_call_id:
                matched_result = result
                break

        if matched_result is None:
            raise ToolResultMissingError(f"Tool result for tool_call_id={tool_call_id} not found")

        ok = matched_result.get("ok")
        if ok is False:
            error_obj = matched_result.get("error")
            error_dict = error_obj if isinstance(error_obj, dict) else {}
            code = error_dict.get("code")
            message = error_dict.get("message")
            if code == "booking_not_confirmed":
                raise BookingNotConfirmedError(str(message) if message else "Booking not confirmed")
            raise BackendToolsResponseError(f"Backend tool failed code={code} message={message}")

        raw_result = matched_result.get("result")
        if not isinstance(raw_result, dict):
            raise ToolResultParseError("Tool result must be a JSON object")

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

    async def _default_post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            data = json.dumps(payload).encode("utf-8")
            merged_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if isinstance(headers, dict) and headers:
                merged_headers.update(headers)
            request = urllib.request.Request(
                url=url,
                data=data,
                method="POST",
                headers=merged_headers,
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
