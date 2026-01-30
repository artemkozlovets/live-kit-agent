from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Callable

from livekit.agents.voice.events import (
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    FunctionToolsExecutedEvent,
    MetricsCollectedEvent,
    SpeechCreatedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

logger = logging.getLogger("livekit-agent.voice-debug")


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def voice_debug_enabled() -> bool:
    return _truthy_env("VOICE_DEBUG")


def _log_pii_enabled() -> bool:
    return _truthy_env("LOG_PII")


def _mask_phone_like(value: str) -> str:
    """Mask phone-like strings unless LOG_PII=1.

    Reason: LiveKit room names can include phone numbers in our current setup.
    """

    if _log_pii_enabled():
        return value

    stripped = value.strip()
    if stripped.startswith("+") and stripped[1:].isdigit() and len(stripped) >= 8:
        return f"+{stripped[1:3]}{'*' * (len(stripped) - 6)}{stripped[-4:]}"
    if stripped.isdigit() and len(stripped) >= 8:
        return f"{'*' * (len(stripped) - 4)}{stripped[-4:]}"
    return value


def _sha1_10(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _safe_text_fields(value: str) -> dict[str, Any]:
    """Return safe-to-log text fields, redacting by default.

    The goal is to keep VOICE_DEBUG usable in production logs while avoiding
    accidental PII leakage. For full transcripts, opt-in with LOG_PII=1.
    """

    value = value or ""
    if _log_pii_enabled():
        return {"text": value}

    if not value:
        return {"text": ""}

    return {
        "text_redacted": True,
        "text_len": len(value),
        "text_sha1_10": _sha1_10(value),
    }


def setup_voice_debug(*, session: Any, room_name: str, job_id: str | None) -> None:
    """Attach high-signal voice/turn logs to an AgentSession.

    Big picture: we want to debug voice issues ("self-talk", lag, interruptions)
    without relying on LiveKit Cloud UI. This logs key session events at INFO
    behind VOICE_DEBUG=1 (with PII masked unless LOG_PII=1).
    """

    if not voice_debug_enabled():
        return

    masked_room = _mask_phone_like(room_name)
    ctx_fields = {"room": masked_room, "job_id": job_id}

    logger.info("VOICE_DEBUG enabled", extra=dict(ctx_fields))

    speech_started_at: dict[str, float] = {}

    def _log(event: str, extra: dict[str, Any] | None = None) -> None:
        payload = dict(ctx_fields)
        payload["voice_debug_event"] = event
        if isinstance(extra, dict):
            payload.update(extra)
        logger.info("VOICE_DEBUG %s", event, extra=payload)

    def _safe(handler_name: str, fn: Callable[[Any], None]) -> Callable[[Any], None]:
        def _wrapped(ev: Any) -> None:
            try:
                fn(ev)
            except Exception:
                logger.exception(
                    "VOICE_DEBUG handler failed",
                    extra={"room": masked_room, "job_id": job_id, "handler": handler_name},
                )

        return _wrapped

    def _on_agent_state(ev: AgentStateChangedEvent) -> None:
        _log(
            "agent_state_changed",
            {
                "old_state": ev.old_state,
                "new_state": ev.new_state,
                "created_at_unix_s": ev.created_at,
            },
        )

    def _on_user_state(ev: UserStateChangedEvent) -> None:
        _log(
            "user_state_changed",
            {
                "old_state": ev.old_state,
                "new_state": ev.new_state,
                "created_at_unix_s": ev.created_at,
            },
        )

    def _on_user_transcript(ev: UserInputTranscribedEvent) -> None:
        fields = _safe_text_fields(ev.transcript)
        fields.update(
            {
                "is_final": ev.is_final,
                "speaker_id": ev.speaker_id,
                "language": ev.language,
                "created_at_unix_s": ev.created_at,
            }
        )
        _log("user_input_transcribed", fields)

    def _on_conversation_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        item_type = getattr(item, "type", None)
        payload: dict[str, Any] = {
            "item_type": item_type,
            "created_at_unix_s": ev.created_at,
        }

        if item_type == "message":
            payload["role"] = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if isinstance(text, str):
                payload.update(_safe_text_fields(text))

        if item_type in {"function_call", "function_call_output"}:
            payload["name"] = getattr(item, "name", None)

        if item_type == "agent_handoff":
            payload["new_agent_id"] = getattr(item, "new_agent_id", None)

        _log("conversation_item_added", payload)

    def _on_speech_created(ev: SpeechCreatedEvent) -> None:
        handle = ev.speech_handle
        speech_id = getattr(handle, "id", None)
        speech_id_str = speech_id if isinstance(speech_id, str) else None

        started_at = time.time()
        if speech_id_str:
            speech_started_at[speech_id_str] = started_at

        _log(
            "speech_created",
            {
                "speech_id": speech_id_str,
                "user_initiated": ev.user_initiated,
                "source": ev.source,
                "created_at_unix_s": ev.created_at,
            },
        )

        def _on_done(_: Any) -> None:
            interrupted = getattr(handle, "interrupted", None)
            elapsed_ms = int((time.time() - started_at) * 1000)
            _log(
                "speech_done",
                {
                    "speech_id": speech_id_str,
                    "interrupted": bool(interrupted) if interrupted is not None else None,
                    "elapsed_ms": elapsed_ms,
                },
            )
            if speech_id_str:
                speech_started_at.pop(speech_id_str, None)

        try:
            handle.add_done_callback(_on_done)
        except Exception:
            # Reason: VOICE_DEBUG must never break the call flow.
            logger.exception(
                "VOICE_DEBUG failed to attach speech done callback",
                extra={"room": masked_room, "job_id": job_id, "speech_id": speech_id_str},
            )

    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        metrics = ev.metrics
        metrics_type = getattr(metrics, "type", None)
        payload: dict[str, Any] = {"metrics_type": metrics_type, "created_at_unix_s": ev.created_at}

        if metrics_type == "realtime_model_metrics":
            payload.update(
                {
                    "label": getattr(metrics, "label", None),
                    "request_id": getattr(metrics, "request_id", None),
                    "duration_s": getattr(metrics, "duration", None),
                    "ttft_s": getattr(metrics, "ttft", None),
                    "cancelled": getattr(metrics, "cancelled", None),
                    "input_tokens": getattr(metrics, "input_tokens", None),
                    "output_tokens": getattr(metrics, "output_tokens", None),
                }
            )
        elif metrics_type in {"llm_metrics", "tts_metrics", "eou_metrics"}:
            # These metrics types are not always emitted for Realtime, but are
            # useful in hybrid/local runs, so include common fields.
            for key in (
                "label",
                "request_id",
                "duration",
                "ttft",
                "ttfb",
                "audio_duration",
                "cancelled",
                "speech_id",
            ):
                if hasattr(metrics, key):
                    payload[key] = getattr(metrics, key, None)

        _log("metrics_collected", payload)

    def _on_tools(ev: FunctionToolsExecutedEvent) -> None:
        names: list[str] = []
        for call in getattr(ev, "function_calls", []) or []:
            name = getattr(call, "name", None)
            if isinstance(name, str) and name:
                names.append(name)

        outputs = getattr(ev, "function_call_outputs", []) or []
        failures = 0
        for output in outputs:
            if output is None:
                continue
            if getattr(output, "is_error", False):
                failures += 1

        _log(
            "function_tools_executed",
            {
                "tool_names": names,
                "tool_count": len(names),
                "tool_failures": failures,
                "created_at_unix_s": ev.created_at,
            },
        )

    def _on_false_interruption(ev: AgentFalseInterruptionEvent) -> None:
        _log(
            "agent_false_interruption",
            {
                "resumed": ev.resumed,
                "created_at_unix_s": ev.created_at,
            },
        )

    session.on("agent_state_changed", _safe("agent_state_changed", _on_agent_state))
    session.on("user_state_changed", _safe("user_state_changed", _on_user_state))
    session.on("user_input_transcribed", _safe("user_input_transcribed", _on_user_transcript))
    session.on("conversation_item_added", _safe("conversation_item_added", _on_conversation_item))
    session.on("speech_created", _safe("speech_created", _on_speech_created))
    session.on("metrics_collected", _safe("metrics_collected", _on_metrics))
    session.on("function_tools_executed", _safe("function_tools_executed", _on_tools))
    session.on("agent_false_interruption", _safe("agent_false_interruption", _on_false_interruption))

