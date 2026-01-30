from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Reason: Some environments (ex: macOS sandboxed terminals) can't query CPU count via sysctl.
# The repo already documents using NUM_CPUS=2 as a workaround.
os.environ.setdefault("NUM_CPUS", "2")

from livekit.agents import Agent  # noqa: E402

from livekit_agent.audio_output_wav import WavFileAudioOutput  # noqa: E402
from livekit_agent.openai_realtime_session import build_openai_realtime_session  # noqa: E402


def _parse_modalities(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",")]
    parts = [p for p in parts if p]
    return parts or None


def _load_turns(*, turns: list[str], turns_file: str | None) -> list[str]:
    if turns_file is None:
        return turns

    lines = Path(turns_file).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def _default_run_dir() -> Path:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    # Reason: Keep smoke artifacts under the same `local-observability/run-*` pattern used elsewhere
    # so they stay out of git status by default (see `.gitignore`).
    return Path("local-observability") / f"run-{run_id}-openai-realtime-audio-smoke"


async def _run(args: argparse.Namespace) -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the realtime audio smoke test.")

    run_dir = Path(args.out_dir) if args.out_dir else _default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    modalities = _parse_modalities(args.modalities)
    voice = (args.voice or "").strip() or None

    audio_path = run_dir / "assistant.wav"
    transcript_path = run_dir / "transcript.json"
    meta_path = run_dir / "meta.json"

    turns = _load_turns(turns=args.turn, turns_file=args.turns_file)
    if not turns:
        turns = ["Please say: 'OpenAI realtime audio smoke test: OK.'"]

    wav_out = WavFileAudioOutput(path=audio_path)
    agent = Agent(
        instructions=(
            "You are running inside an automated audio smoke test.\n"
            "Always respond with a short, spoken answer.\n"
            "Avoid markdown.\n"
        )
    )

    started_at = time.time()
    transcript_turns: list[dict[str, Any]] = []
    llm_to_close: Any = None
    try:
        async with build_openai_realtime_session(modalities=modalities, voice=voice) as session:
            llm_to_close = session.llm
            session.output.audio = wav_out
            await session.start(agent, record=False)

            for user_text in turns:
                seg_start = len(wav_out.segments)
                handle = session.generate_reply(user_input=user_text)
                await asyncio.wait_for(handle.wait_for_playout(), timeout=float(args.timeout_s))
                seg_end = len(wav_out.segments)

                assistant_text = ""
                for item in reversed(handle.chat_items):
                    if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
                        assistant_text = getattr(item, "text_content", None) or ""
                        break

                transcript_turns.append(
                    {
                        "user": user_text,
                        "assistant": assistant_text,
                        "segments": [
                            {
                                "segment_index": seg.segment_index,
                                "start_sample": seg.start_sample,
                                "num_samples": seg.num_samples,
                                "duration_s": seg.duration_s,
                                "sample_rate": seg.sample_rate,
                                "num_channels": seg.num_channels,
                                "interrupted": seg.interrupted,
                            }
                            for seg in wav_out.segments[seg_start:seg_end]
                        ],
                    }
                )
    finally:
        wav_out.close()
        aclose = getattr(llm_to_close, "aclose", None)
        if callable(aclose):
            res = aclose()
            if asyncio.iscoroutine(res):
                await res

    duration_s = time.time() - started_at

    transcript_payload = {
        "audio_path": str(audio_path),
        "turns": transcript_turns,
    }
    transcript_path.write_text(json.dumps(transcript_payload, indent=2, sort_keys=True), encoding="utf-8")

    meta_payload = {
        "started_at": started_at,
        "duration_s": duration_s,
        "voice": voice,
        "modalities": modalities,
        "turn_count": len(turns),
        "audio": {
            "path": str(audio_path),
            "total_samples": wav_out.total_samples,
            "segments": [seg.__dict__ for seg in wav_out.segments],
        },
    }
    meta_path.write_text(json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8")

    if wav_out.total_samples <= 0:
        print(
            "ERROR: No audio frames were captured. This usually means the model did not produce audio output "
            "(check --modalities and --voice).",
            file=sys.stderr,
        )
        print(f"Artifacts saved under: {run_dir}", file=sys.stderr)
        return 2

    print(f"Run dir: {run_dir}")
    print(f"Audio:   {audio_path}")
    print(f"Transcript: {transcript_path}")
    print(f"Meta:    {meta_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI Realtime audio smoke test (no microphone).")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: timestamped under local-observability/).")
    parser.add_argument("--turn", action="append", default=[], help="User text input (repeatable).")
    parser.add_argument("--turns-file", default=None, help="Text file with one user turn per line.")
    parser.add_argument("--voice", default=os.environ.get("OPENAI_REALTIME_VOICE"), help="Voice name (default: OPENAI_REALTIME_VOICE).")
    parser.add_argument(
        "--modalities",
        default=os.environ.get("OPENAI_REALTIME_MODALITIES", "text,audio"),
        help="Comma-separated list (default: text,audio or OPENAI_REALTIME_MODALITIES).",
    )
    parser.add_argument("--timeout-s", default="60", help="Per-turn timeout in seconds (default: 60).")

    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
