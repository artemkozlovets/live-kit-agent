import logging

import pytest


class _FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, list[object]] = {}

    def on(self, event: str, cb: object) -> None:
        self.handlers.setdefault(event, []).append(cb)


def test_setup_voice_debug_registers_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_DEBUG", "1")

    from livekit_agent.voice_debug import setup_voice_debug

    session = _FakeSession()
    setup_voice_debug(session=session, room_name="+13053179840_room", job_id="job-1")

    assert set(session.handlers.keys()) == {
        "agent_state_changed",
        "user_state_changed",
        "user_input_transcribed",
        "conversation_item_added",
        "speech_created",
        "metrics_collected",
        "function_tools_executed",
        "agent_false_interruption",
    }


def test_setup_voice_debug_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_DEBUG", raising=False)

    from livekit_agent.voice_debug import setup_voice_debug

    session = _FakeSession()
    setup_voice_debug(session=session, room_name="room-1", job_id="job-1")

    assert session.handlers == {}


def test_voice_debug_handlers_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_DEBUG", "1")

    from livekit_agent.voice_debug import setup_voice_debug

    session = _FakeSession()
    setup_voice_debug(session=session, room_name="room-1", job_id="job-1")

    handler = session.handlers["agent_state_changed"][0]

    # Should swallow exceptions from malformed events.
    logging.getLogger("livekit-agent.voice-debug").setLevel(logging.INFO)
    handler(object())

