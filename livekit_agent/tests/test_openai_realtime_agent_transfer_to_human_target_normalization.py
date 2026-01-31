from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit import rtc  # noqa: E402

from livekit_agent.openai_realtime_agent import (  # noqa: E402
    OpenAIRealtimeAgent,
    _normalize_sip_transfer_target,
)


def test_normalize_sip_transfer_target_upgrades_bare_phone_number() -> None:
    normalized, err = _normalize_sip_transfer_target("305-317-9840")
    assert err is None
    assert normalized == "tel:+13053179840"


def test_normalize_sip_transfer_target_strips_tel_punctuation() -> None:
    normalized, err = _normalize_sip_transfer_target("tel:+1 305 317-9840")
    assert err is None
    assert normalized == "tel:+13053179840"


@pytest.mark.asyncio
async def test_transfer_to_human_rejects_invalid_transfer_target(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = object()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    class _Room:
        name = "room-test"

    monkeypatch.setenv("HUMAN_TRANSFER_TO", "not-a-uri")
    monkeypatch.setattr(agent, "_get_session_room", lambda: _Room())

    called = False

    async def fake_sip_transfer(**kwargs: Any) -> None:
        nonlocal called
        called = True
        _ = kwargs

    monkeypatch.setattr(agent, "_sip_transfer", fake_sip_transfer)

    result = await agent._transfer_to_human()

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_transfer_target"
    assert called is False


@pytest.mark.asyncio
async def test_transfer_to_human_calls_sip_transfer_with_normalized_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = object()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    class _Participant:
        kind = rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        identity = "sip-caller"

    class _Room:
        name = "room-test"
        remote_participants = {"p1": _Participant()}

    monkeypatch.setenv("HUMAN_TRANSFER_TO", "305 317 9840")
    monkeypatch.setattr(agent, "_get_session_room", lambda: _Room())

    seen: dict[str, str] = {}

    async def fake_sip_transfer(*, room_name: str, participant_identity: str, transfer_to: str) -> None:
        seen["room_name"] = room_name
        seen["participant_identity"] = participant_identity
        seen["transfer_to"] = transfer_to

    monkeypatch.setattr(agent, "_sip_transfer", fake_sip_transfer)

    result = await agent._transfer_to_human()

    assert result == {"ok": True, "transfer_to": "tel:+13053179840"}
    assert seen == {
        "room_name": "room-test",
        "participant_identity": "sip-caller",
        "transfer_to": "tel:+13053179840",
    }


@pytest.mark.asyncio
async def test_transfer_to_human_maps_livekit_phone_number_transfer_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = object()
    agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-test")  # type: ignore[arg-type]

    class _Participant:
        kind = rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        identity = "sip-caller"

    class _Room:
        name = "room-test"
        remote_participants = {"p1": _Participant()}

    monkeypatch.setenv("HUMAN_TRANSFER_TO", "tel:+13053179840")
    monkeypatch.setattr(agent, "_get_session_room", lambda: _Room())

    async def fake_sip_transfer(*, room_name: str, participant_identity: str, transfer_to: str) -> None:
        _ = room_name, participant_identity, transfer_to
        raise RuntimeError("TwirpError(code=unknown, message=we don't yet support transfers for this phone number type, status=500)")

    monkeypatch.setattr(agent, "_sip_transfer", fake_sip_transfer)

    result = await agent._transfer_to_human()

    assert result["ok"] is False
    assert result["error"]["code"] == "transfer_not_supported"
