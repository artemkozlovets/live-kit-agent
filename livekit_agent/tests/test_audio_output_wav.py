from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    from livekit import rtc  # noqa: F401
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit runtime unavailable in this environment: {exc}", allow_module_level=True)

from livekit import rtc  # noqa: E402

from livekit_agent.audio_output_wav import WavFileAudioOutput  # noqa: E402


@pytest.mark.asyncio
async def test_wav_audio_output_writes_audio_and_emits_playout(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    out = WavFileAudioOutput(path=path)
    try:
        await out.capture_frame(
            rtc.AudioFrame(
                data=b"\x01\x00" * 100,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=100,
            )
        )
        await out.capture_frame(
            rtc.AudioFrame(
                data=b"\x02\x00" * 200,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=200,
            )
        )
        out.flush()
        ev = await out.wait_for_playout()
    finally:
        out.close()

    assert ev.interrupted is False
    assert ev.playback_position > 0
    assert out.total_samples == 300
    assert len(out.segments) == 1
    assert out.segments[0].num_samples == 300

    with wave.open(str(out.path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 24000
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 300


@pytest.mark.asyncio
async def test_wav_audio_output_flush_without_frames_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    out = WavFileAudioOutput(path=path)
    try:
        out.flush()
        _ = await out.wait_for_playout()
    finally:
        out.close()

    assert not path.exists()
    assert out.total_samples == 0
    assert out.segments == []


@pytest.mark.asyncio
async def test_wav_audio_output_rejects_mismatched_sample_rate(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    out = WavFileAudioOutput(path=path)
    try:
        await out.capture_frame(
            rtc.AudioFrame(
                data=b"\x00\x00" * 10,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=10,
            )
        )

        with pytest.raises(ValueError, match="consistent audio params"):
            await out.capture_frame(
                rtc.AudioFrame(
                    data=b"\x00\x00" * 10,
                    sample_rate=48000,
                    num_channels=1,
                    samples_per_channel=10,
                )
            )
    finally:
        out.close()
