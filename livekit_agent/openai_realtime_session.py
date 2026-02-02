from __future__ import annotations

import os
from typing import Any

from livekit.agents import AgentSession


def _float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _bool_env(name: str) -> bool | None:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return None


def build_openai_realtime_session(*, modalities: list[str] | None = None, voice: str | None = None) -> AgentSession:
    """Build an AgentSession configured for OpenAI Realtime.

    Note: The OpenAI plugin is an optional dependency (`livekit-agents[openai]`).
    """

    try:
        from livekit.plugins import openai  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "OpenAI Realtime plugin not installed. Install `livekit-agents[openai]` to use /tools cutover."
        ) from exc

    kwargs: dict[str, Any] = {}
    session_kwargs: dict[str, Any] = {}

    if isinstance(modalities, list) and modalities:
        kwargs["modalities"] = list(modalities)
    if isinstance(voice, str) and voice.strip():
        kwargs["voice"] = voice.strip()
    # Reason: We rely on the agent hooks (on_enter/on_user_turn_completed) to decide
    # when to speak (including backend-first tool calls). Disable OpenAI's automatic
    # response creation so the model doesn't generate replies on VAD events before
    # our code can inject case status / guardrails.
    try:
        from openai.types.beta.realtime.session import TurnDetection  # type: ignore

        eagerness = os.getenv("OPENAI_REALTIME_EAGERNESS", "").strip().lower() or "auto"
        if eagerness not in {"auto", "low", "medium", "high"}:
            eagerness = "auto"

        kwargs["turn_detection"] = TurnDetection(
            type="semantic_vad",
            eagerness=eagerness,
            create_response=False,
            interrupt_response=False,
        )
    except Exception:  # pragma: no cover
        # If TurnDetection isn't available for some reason, fall back to plugin defaults.
        pass

    min_interruption_duration = _float_env("LK_MIN_INTERRUPTION_DURATION_S")
    if min_interruption_duration is not None and min_interruption_duration >= 0:
        session_kwargs["min_interruption_duration"] = min_interruption_duration

    min_interruption_words = _int_env("LK_MIN_INTERRUPTION_WORDS")
    if min_interruption_words is not None and min_interruption_words >= 0:
        session_kwargs["min_interruption_words"] = min_interruption_words

    false_interruption_timeout = _float_env("LK_FALSE_INTERRUPTION_TIMEOUT_S")
    if false_interruption_timeout is not None:
        if false_interruption_timeout < 0:
            session_kwargs["false_interruption_timeout"] = None
        else:
            session_kwargs["false_interruption_timeout"] = false_interruption_timeout

    resume_false_interruption = _bool_env("LK_RESUME_FALSE_INTERRUPTION")
    if resume_false_interruption is not None:
        session_kwargs["resume_false_interruption"] = resume_false_interruption

    llm = openai.realtime.RealtimeModel(**kwargs)
    return AgentSession(llm=llm, **session_kwargs)
