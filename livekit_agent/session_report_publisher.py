from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger("livekit-agent-vapi-adapter.session-report")

PostJson = Callable[[str, dict[str, Any], dict[str, str]], Awaitable[dict[str, Any]]]


def _to_report_dict(report: object) -> dict[str, Any]:
    """Best-effort conversion of a LiveKit SessionReport to a dict.

    LiveKit docs recommend using `.to_dict()`. We keep a couple fallbacks so this
    remains resilient across SDK versions.
    """

    to_dict = getattr(report, "to_dict", None)
    if callable(to_dict):
        out = to_dict()
        if isinstance(out, dict):
            return out

    model_dump = getattr(report, "model_dump", None)
    if callable(model_dump):
        out = model_dump(exclude_none=True)
        if isinstance(out, dict):
            return out

    return {}


@dataclass(frozen=True)
class SessionReportPublisher:
    """Publish LiveKit Agent session reports to an HTTP endpoint."""

    reports_url: str
    token: str | None = None
    post_json: PostJson | None = None
    timeout_s: float = 10.0

    async def publish(self, ctx: object) -> None:
        """Publish a session report for ctx, swallowing errors.

        Reason: session reports are best-effort telemetry; failures should not
        crash the agent worker.
        """

        if not self.reports_url.strip():
            return

        room = getattr(ctx, "room", None)
        room_name = getattr(room, "name", None)
        room_name_str = room_name if isinstance(room_name, str) else ""

        make_report = getattr(ctx, "make_session_report", None)
        if not callable(make_report):
            logger.warning("JobContext missing make_session_report(); skipping publish")
            return

        try:
            report_obj = make_report()
            report_dict = _to_report_dict(report_obj)
            payload = {"room_name": room_name_str, "report": report_dict}

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            post = self.post_json or self._default_post_json
            await post(self.reports_url, payload, headers)
        except Exception as exc:
            logger.warning(
                "Failed to publish session report",
                extra={"room": room_name_str},
                exc_info=exc,
            )

    async def _default_post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url=url,
                data=data,
                method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    status = getattr(response, "status", None)
                    body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
                raise RuntimeError(f"Session report endpoint returned HTTP {exc.code}: {body}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError("Session report endpoint connection failed") from exc

            if status is None or status < 200 or status >= 300:
                raise RuntimeError(f"Session report endpoint returned HTTP {status}: {body}")

            if not body.strip():
                return {}

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                # Endpoint doesn't have to return JSON; ignore body.
                return {}

            return parsed if isinstance(parsed, dict) else {}

        return await asyncio.to_thread(_send)

