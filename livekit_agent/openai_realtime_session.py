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
    # Reason: We rely on the agent hooks (on_enter/on_user_turn_completed) to decide
    # when to speak (including backend-first tool calls). Disable OpenAI's automatic
    # response creation so the model doesn't generate replies on VAD events before
    # our code can inject case status / guardrails.
    try:
        from openai.types.beta.realtime.session import TurnDetection  # type: ignore

        kwargs["turn_detection"] = TurnDetection(
            type="semantic_vad",
            eagerness="auto",
            create_response=False,
            interrupt_response=False,
        )
    except Exception:  # pragma: no cover
        # If TurnDetection isn't available for some reason, fall back to plugin defaults.
        pass

    llm = openai.realtime.RealtimeModel(**kwargs)
    return AgentSession(llm=llm)
