from __future__ import annotations

import json
import logging
import os
import re
import traceback
from typing import Any

from dotenv import load_dotenv

# Load `.env` early so CLI options (LIVEKIT_*) and NUM_CPUS are available during
# `livekit.agents` import and initialization.
load_dotenv()

from livekit import rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.agents.voice.events import CloseEvent, ErrorEvent

from livekit_agent.backend_tools_client import BackendToolsClient
from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent
from livekit_agent.openai_realtime_session import build_openai_realtime_session
from livekit_agent.session_report_publisher import SessionReportPublisher

logger = logging.getLogger("livekit-agent")


_AUTH_HEADER_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Common auth header patterns that can leak secrets into logs.
    (re.compile(r"(Authorization['\"]:\s*['\"]Token\s+)[^'\"]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Authorization['\"]:\s*['\"]Bearer\s+)[^'\"]+", re.IGNORECASE), r"\1***"),
)

_LOG_RECORD_BUILTINS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}


def _register_openai_realtime_plugin_on_main_thread() -> None:
    try:
        # Reason: LiveKit plugins must be registered on the main thread. Importing here
        # ensures the OpenAI plugin registers before worker threads start.
        from livekit.plugins import openai  # noqa: F401
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "OpenAI Realtime plugin not installed. Install `livekit-agents[openai]`."
        ) from exc


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts_unix_s": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_BUILTINS:
                continue
            extra[key] = value
        if extra:
            payload["extra"] = extra

        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(payload, ensure_ascii=True, default=str)


def _maybe_enable_local_file_logging() -> None:
    local_dir = os.getenv("LOCAL_OBSERVABILITY_DIR", "").strip()
    if not local_dir:
        return

    os.makedirs(local_dir, exist_ok=True)
    log_path = os.path.join(local_dir, "agent.log.jsonl")

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(_JsonLogFormatter())
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    if any(getattr(h, "baseFilename", None) == handler.baseFilename for h in root.handlers):
        return
    root.addHandler(handler)


def _redact_secrets(text: str) -> str:
    redacted = text
    for pattern, replacement in _AUTH_HEADER_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _truthy_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        logger.warning("Invalid %s=%r (expected int); ignoring", name, raw)
        return None
    return int(raw)


def _build_server() -> AgentServer:
    kwargs: dict[str, Any] = {}
    host = os.getenv("HOST", "").strip() or os.getenv("LIVEKIT_WORKER_HOST", "").strip()
    if host:
        kwargs["host"] = host

    port = _int_env("PORT") or _int_env("LIVEKIT_WORKER_PORT")
    if port is not None:
        kwargs["port"] = port

    prometheus_port = _int_env("PROMETHEUS_PORT") or _int_env("LIVEKIT_PROMETHEUS_PORT")
    if prometheus_port is not None:
        kwargs["prometheus_port"] = prometheus_port

    prometheus_multiproc_dir = (
        os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
        or os.getenv("LIVEKIT_PROMETHEUS_MULTIPROC_DIR", "").strip()
    )
    if prometheus_multiproc_dir:
        kwargs["prometheus_multiproc_dir"] = prometheus_multiproc_dir

    return AgentServer(**kwargs)


def _extract_sip_phone_number(room: rtc.Room) -> str | None:
    for participant in room.remote_participants.values():
        if getattr(participant, "kind", None) != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            continue

        attrs = participant.attributes or {}
        phone = attrs.get("sip.phoneNumber")
        if isinstance(phone, str) and phone.strip():
            return phone.strip()

        identity = getattr(participant, "identity", "")
        if isinstance(identity, str) and identity.strip().startswith("+") and identity.strip()[1:].isdigit():
            return identity.strip()

    return None


server = _build_server()

DEFAULT_BACKEND_TOOLS_URL = "https://call-agent-development.up.railway.app/tools"


async def _on_session_end(ctx: JobContext) -> None:
    """Publish a session report (optional).

    Reason: we want a programmatic artifact (session report JSON) without having
    to open the LiveKit Cloud UI.
    """

    reports_url = os.getenv("SESSION_REPORTS_URL", "").strip()
    if not reports_url:
        return

    token = os.getenv("SESSION_REPORTS_TOKEN", "").strip() or None
    publisher = SessionReportPublisher(reports_url=reports_url, token=token)
    await publisher.publish(ctx)


@server.rtc_session(agent_name=os.getenv("LIVEKIT_AGENT_NAME", "").strip(), on_session_end=_on_session_end)
async def entrypoint(ctx: JobContext) -> None:
    load_dotenv()
    ctx.log_context_fields = {"room": ctx.room.name}

    backend_tools_url = os.getenv("BACKEND_TOOLS_URL", DEFAULT_BACKEND_TOOLS_URL)
    voice = os.getenv("OPENAI_REALTIME_VOICE", "").strip() or None
    use_backend_guardrails = _truthy_env("AGENT_BACKEND_GUARDRAILS", default=True)

    sip_phone_number = _extract_sip_phone_number(ctx.room)

    logger.info(
        "starting agent session",
        extra={
            "backend_tools_url": backend_tools_url,
            "openai_realtime_voice": voice,
            "use_backend_guardrails": use_backend_guardrails,
            "has_openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
            "has_sip_phone_number": bool(sip_phone_number),
        },
    )

    session = build_openai_realtime_session(voice=voice)
    agent: Agent = OpenAIRealtimeAgent(
        backend_client=BackendToolsClient(tools_url=backend_tools_url),
        use_backend_guardrails=use_backend_guardrails,
        call_id_fallback=ctx.room.name,
        sip_phone_number=sip_phone_number,
    )

    @session.on("error")
    def _on_session_error(ev: ErrorEvent) -> None:
        # Reason: LiveKit Cloud "AgentSession is closing..." logs can omit the underlying exception.
        # Log the full error details (including traceback when available) so we can debug via `lk agent logs`.
        error_obj = ev.error
        underlying_exc = getattr(error_obj, "error", None)
        exc_info = None

        if isinstance(underlying_exc, BaseException) and underlying_exc.__traceback__ is not None:
            # Reason: Some exceptions include request headers in their message (can leak API keys).
            redacted_exc = RuntimeError(_redact_secrets(str(underlying_exc)))
            exc_info = (type(redacted_exc), redacted_exc, underlying_exc.__traceback__)
        elif isinstance(error_obj, BaseException) and error_obj.__traceback__ is not None:
            redacted_exc = RuntimeError(_redact_secrets(str(error_obj)))
            exc_info = (type(redacted_exc), redacted_exc, error_obj.__traceback__)

        recoverable = getattr(error_obj, "recoverable", None)
        label = getattr(error_obj, "label", None)
        error_type = getattr(error_obj, "type", None)
        status = getattr(underlying_exc, "status", None)
        remote_error = None
        headers = getattr(underlying_exc, "headers", None)
        if headers:
            remote_error = headers.get("x-error")

        logger.error(
            "AgentSession error",
            extra={
                "room": ctx.room.name,
                "job_id": getattr(ctx, "job", None).id if getattr(ctx, "job", None) else None,
                "error_model_type": type(error_obj).__name__,
                "error_type": error_type,
                "error_label": label,
                "recoverable": recoverable,
                "source_type": type(ev.source).__name__,
                "status": status,
                "remote_error": remote_error,
            },
            exc_info=exc_info,
        )

    @session.on("close")
    def _on_session_close(ev: CloseEvent) -> None:
        close_error = getattr(ev, "error", None)
        close_error_dump = None
        if close_error is not None and hasattr(close_error, "model_dump"):
            close_error_dump = close_error.model_dump(exclude_none=True)

        logger.info(
            "AgentSession closing",
            extra={
                "room": ctx.room.name,
                "job_id": getattr(ctx, "job", None).id if getattr(ctx, "job", None) else None,
                "reason": getattr(ev, "reason", None),
                "error": close_error_dump,
            },
        )

    try:
        await session.start(agent=agent, room=ctx.room)
    except Exception:
        # Reason: Ensure *any* uncaught exception is visible in LiveKit Cloud logs.
        logger.exception("Unhandled exception in agent entrypoint", extra={"room": ctx.room.name})
        raise


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    _maybe_enable_local_file_logging()
    _register_openai_realtime_plugin_on_main_thread()
    cli.run_app(server)

