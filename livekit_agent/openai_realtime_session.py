from __future__ import annotations

from typing import Any

from livekit.agents import AgentSession


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
    if isinstance(modalities, list) and modalities:
        kwargs["modalities"] = list(modalities)
    if isinstance(voice, str) and voice.strip():
        kwargs["voice"] = voice.strip()

    llm = openai.realtime.RealtimeModel(**kwargs)
    return AgentSession(llm=llm)

