from __future__ import annotations

import os
import sys
import types

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)


def test_openai_realtime_session_defaults_to_buffering_uninterruptible_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("LK_DISCARD_AUDIO_IF_UNINTERRUPTIBLE", raising=False)

    captured_session_kwargs: dict[str, object] = {}

    class FakeAgentSession:
        def __init__(self, **kwargs: object) -> None:
            captured_session_kwargs.update(kwargs)

    class FakeRealtimeModel:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs

    fake_openai = types.ModuleType("livekit.plugins.openai")
    fake_openai.realtime = types.SimpleNamespace(RealtimeModel=FakeRealtimeModel)
    monkeypatch.setitem(sys.modules, "livekit.plugins.openai", fake_openai)

    from livekit_agent import openai_realtime_session as mod

    monkeypatch.setattr(mod, "AgentSession", FakeAgentSession)

    session = mod.build_openai_realtime_session(modalities=["text"])
    assert session is not None

    assert captured_session_kwargs.get("discard_audio_if_uninterruptible") is False


def test_openai_realtime_session_allows_overriding_discard_audio_if_uninterruptible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("LK_DISCARD_AUDIO_IF_UNINTERRUPTIBLE", "true")

    captured_session_kwargs: dict[str, object] = {}

    class FakeAgentSession:
        def __init__(self, **kwargs: object) -> None:
            captured_session_kwargs.update(kwargs)

    class FakeRealtimeModel:
        def __init__(self, **kwargs: object) -> None:
            _ = kwargs

    fake_openai = types.ModuleType("livekit.plugins.openai")
    fake_openai.realtime = types.SimpleNamespace(RealtimeModel=FakeRealtimeModel)
    monkeypatch.setitem(sys.modules, "livekit.plugins.openai", fake_openai)

    from livekit_agent import openai_realtime_session as mod

    monkeypatch.setattr(mod, "AgentSession", FakeAgentSession)

    session = mod.build_openai_realtime_session(modalities=["text"])
    assert session is not None

    assert captured_session_kwargs.get("discard_audio_if_uninterruptible") is True

