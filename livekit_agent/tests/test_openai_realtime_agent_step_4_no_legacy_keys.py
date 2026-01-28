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


def test_openai_realtime_session_does_not_require_legacy_vendor_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    captured: dict[str, object] = {}

    class FakeRealtimeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake_openai = types.ModuleType("livekit.plugins.openai")
    fake_openai.realtime = types.SimpleNamespace(RealtimeModel=FakeRealtimeModel)
    sys.modules["livekit.plugins.openai"] = fake_openai

    from livekit_agent.openai_realtime_session import build_openai_realtime_session

    # Act
    session = build_openai_realtime_session(modalities=["text"])

    # Assert
    assert session is not None
    assert captured.get("modalities") == ["text"]

