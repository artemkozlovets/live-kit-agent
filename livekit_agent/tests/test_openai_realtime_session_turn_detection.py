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


def test_openai_realtime_session_disables_auto_response_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    captured: dict[str, object] = {}

    class FakeRealtimeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_openai = types.ModuleType("livekit.plugins.openai")
    fake_openai.realtime = types.SimpleNamespace(RealtimeModel=FakeRealtimeModel)
    monkeypatch.setitem(sys.modules, "livekit.plugins.openai", fake_openai)

    from livekit_agent.openai_realtime_session import build_openai_realtime_session

    session = build_openai_realtime_session(modalities=["text"])
    assert session is not None

    turn_detection = captured.get("turn_detection")
    assert turn_detection is not None
    assert getattr(turn_detection, "create_response", None) is False

