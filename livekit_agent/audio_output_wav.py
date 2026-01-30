from __future__ import annotations

import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from livekit import rtc
from livekit.agents.voice import io


@dataclass(frozen=True)
class WavSegment:
    segment_index: int
    start_sample: int
    num_samples: int
    sample_rate: int
    num_channels: int
    interrupted: bool

    @property
    def duration_s(self) -> float:
        return self.num_samples / self.sample_rate


class WavFileAudioOutput(io.AudioOutput):
    """Capture agent output audio to a WAV file.

    Big picture:
    - LiveKit Agents expects an `io.AudioOutput` sink when not running in a room.
    - This sink writes raw PCM16 frames to a .wav (no extra deps like PyAV).
    - It also emits playback_started / playback_finished so SpeechHandle waits resolve.
    """

    def __init__(self, *, path: str | Path, sample_rate: int | None = None) -> None:
        super().__init__(
            label="WavFileAudioOutput",
            capabilities=io.AudioOutputCapabilities(pause=False),
            next_in_chain=None,
            sample_rate=sample_rate,
        )
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._wav: wave.Wave_write | None = None
        self._wav_fp: BinaryIO | None = None
        self._opened_params: tuple[int, int] | None = None  # (sample_rate, num_channels)

        self._total_samples = 0
        self._segment_active = False
        self._segment_start_sample = 0
        self._segment_samples = 0
        self._segment_interrupted = False
        self._segment_index = 0
        self._segments: list[WavSegment] = []

    @property
    def path(self) -> Path:
        return self._path

    @property
    def total_samples(self) -> int:
        return self._total_samples

    @property
    def segments(self) -> list[WavSegment]:
        return list(self._segments)

    def close(self) -> None:
        if self._wav is None:
            return
        self._wav.close()
        self._wav = None
        self._wav_fp = None

    def _ensure_open(self, *, frame: rtc.AudioFrame) -> None:
        if self._wav is not None:
            return

        sample_rate = frame.sample_rate
        num_channels = frame.num_channels

        self._wav_fp = self._path.open("wb")
        self._wav = wave.open(self._wav_fp, "wb")
        self._wav.setnchannels(num_channels)
        self._wav.setsampwidth(2)  # int16
        self._wav.setframerate(sample_rate)
        self._opened_params = (sample_rate, num_channels)

    def _validate_params(self, *, frame: rtc.AudioFrame) -> None:
        if self._opened_params is None:
            return

        sample_rate, num_channels = self._opened_params
        if frame.sample_rate != sample_rate or frame.num_channels != num_channels:
            raise ValueError(
                "WavFileAudioOutput requires consistent audio params; "
                f"got sample_rate={frame.sample_rate}Hz channels={frame.num_channels}, "
                f"expected sample_rate={sample_rate}Hz channels={num_channels}"
            )

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)

        self._ensure_open(frame=frame)
        self._validate_params(frame=frame)
        assert self._wav is not None
        assert self._opened_params is not None

        if not self._segment_active:
            self._segment_active = True
            self._segment_start_sample = self._total_samples
            self._segment_samples = 0
            self._segment_interrupted = False
            self._segment_index += 1
            self.on_playback_started(created_at=time.time())

        self._wav.writeframes(frame.data.tobytes())
        self._total_samples += frame.samples_per_channel
        self._segment_samples += frame.samples_per_channel

    def flush(self) -> None:
        super().flush()

        if not self._segment_active:
            return

        assert self._opened_params is not None
        sample_rate, num_channels = self._opened_params

        seg = WavSegment(
            segment_index=self._segment_index,
            start_sample=self._segment_start_sample,
            num_samples=self._segment_samples,
            sample_rate=sample_rate,
            num_channels=num_channels,
            interrupted=self._segment_interrupted,
        )
        self._segments.append(seg)

        playback_position = seg.duration_s
        interrupted = seg.interrupted
        self._segment_active = False
        self._segment_samples = 0
        self._segment_interrupted = False
        self.on_playback_finished(playback_position=playback_position, interrupted=interrupted)

    def clear_buffer(self) -> None:
        if not self._segment_active:
            return
        # Reason: This sink writes frames immediately; "clear_buffer" means we stop the current
        # segment right away and mark it as interrupted for downstream waits/metrics.
        self._segment_interrupted = True
        self.flush()
