from __future__ import annotations

import argparse
import asyncio
import os
import time
from typing import Any

# Reason: Some environments (ex: macOS sandboxed terminals) can't query CPU count via sysctl.
# The repo already documents using NUM_CPUS=2 as a workaround.
os.environ.setdefault("NUM_CPUS", "2")

from livekit.agents import AgentSession  # noqa: E402

from livekit_agent.openai_realtime_agent import OpenAIRealtimeAgent  # noqa: E402
from livekit_agent.openai_realtime_session import build_openai_realtime_session  # noqa: E402


class _Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {
                "tool_name": kwargs.get("tool_name"),
                "tool_arguments": kwargs.get("tool_arguments"),
            }
        )
        return {"customer": {"id": None, "first_name": None}}


def _extract_spoken_greeting(instructions: str) -> str:
    # `instructions` can contain multiple lines (language lock + greeting).
    marker = "Say exactly:"
    idx = instructions.lower().find(marker.lower())
    if idx == -1:
        raise RuntimeError("Expected greeting instructions to contain 'Say exactly:'")
    return instructions[idx + len(marker) :].strip()


class _Ev:
    pass


async def _wait_for(predicate: Any, *, timeout_s: float, poll_s: float = 0.01) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(poll_s)
    raise TimeoutError("Timed out waiting for condition")


def _temp_env(overrides: dict[str, str | None]) -> Any:
    class _Manager:
        def __init__(self, values: dict[str, str | None]) -> None:
            self._values = values
            self._previous: dict[str, str | None] = {}

        def __enter__(self) -> None:
            for key, value in self._values.items():
                self._previous[key] = os.environ.get(key)
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            for key, prev in self._previous.items():
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev

    return _Manager(overrides)


async def _scenario_session_options() -> None:
    # This should not perform any network I/O; it only validates local session options.
    os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
    session = build_openai_realtime_session(modalities=["text"])
    discard = getattr(session.options, "discard_audio_if_uninterruptible", None)
    if discard is not False:
        raise RuntimeError(f"Expected discard_audio_if_uninterruptible=False by default, got {discard!r}")
    await session.aclose()


async def _scenario_greeting_echo_filter() -> None:
    # Make this fast/deterministic.
    with _temp_env(
        {
            "REALTIME_TRANSCRIPT_DEBOUNCE_S": "0.05",
            "REALTIME_TRANSCRIPT_POST_SILENCE_S": "0.0",
            "REALTIME_TRANSCRIPT_MAX_WAIT_S": "1.0",
        }
    ):
        backend = _Backend()
        agent = OpenAIRealtimeAgent(
            backend_client=backend,  # type: ignore[arg-type]
            call_id_fallback="room-smoke",
            sip_phone_number="+15551234567",
        )

        seen_instructions: list[str] = []
        async with AgentSession() as session:
            def fake_generate_reply(*, instructions: Any = None, **kwargs: Any) -> None:
                _ = kwargs
                if instructions is not None:
                    seen_instructions.append(str(instructions))

            session.generate_reply = fake_generate_reply  # type: ignore[assignment]

            await session.start(agent)
            await agent.on_enter()

            if backend.calls != [{"tool_name": "get_case_status", "tool_arguments": {"last_user_message": " "}}]:
                raise RuntimeError(f"Unexpected backend calls after greeting: {backend.calls!r}")
            if not seen_instructions:
                raise RuntimeError("Expected a phone greeting to be generated")

            spoken_greeting = _extract_spoken_greeting(seen_instructions[-1])

            # Simulate echo/self-talk: the greeting itself gets transcribed as "user" input.
            ev1 = _Ev()
            ev1.is_final = True
            ev1.transcript = spoken_greeting
            ev1.created_at = 123.0
            session.emit("user_input_transcribed", ev1)  # type: ignore[arg-type]

            await asyncio.sleep(0.2)
            if len(backend.calls) != 1:
                raise RuntimeError(f"Greeting echo should be ignored, but backend calls grew: {backend.calls!r}")

            # Now emit a real user utterance; it should trigger the turn loop.
            ev2 = _Ev()
            ev2.is_final = True
            ev2.transcript = "I need help with a flat tire"
            ev2.created_at = 124.0
            session.emit("user_input_transcribed", ev2)  # type: ignore[arg-type]

            await _wait_for(lambda: len(backend.calls) == 2, timeout_s=2.0)
            if backend.calls[1]["tool_name"] != "get_case_status":
                raise RuntimeError(f"Expected get_case_status call, got: {backend.calls[1]!r}")


async def _scenario_turn_latency(*, max_s: float) -> None:
    # Validate the default debounce is fast enough (regression guard for "slow after you stop talking").
    with _temp_env(
        {
            "REALTIME_TRANSCRIPT_DEBOUNCE_S": None,
            "REALTIME_TRANSCRIPT_POST_SILENCE_S": None,
            "REALTIME_TRANSCRIPT_MAX_WAIT_S": None,
        }
    ):
        backend = _Backend()
        agent = OpenAIRealtimeAgent(backend_client=backend, call_id_fallback="room-smoke")  # type: ignore[arg-type]

        reply_called = asyncio.Event()
        reply_at = 0.0

        async with AgentSession() as session:
            def fake_generate_reply(**kwargs: Any) -> None:
                nonlocal reply_at
                _ = kwargs
                reply_at = time.monotonic()
                reply_called.set()

            session.generate_reply = fake_generate_reply  # type: ignore[assignment]

            await session.start(agent)
            await agent.on_enter()

            t0 = time.monotonic()
            ev = _Ev()
            ev.is_final = True
            ev.transcript = "Hello"
            ev.created_at = 123.0
            session.emit("user_input_transcribed", ev)  # type: ignore[arg-type]

            await asyncio.wait_for(reply_called.wait(), timeout=2.0)

        elapsed = reply_at - t0
        print(f"turn_latency_s={elapsed:.3f}")
        if elapsed > max_s:
            raise RuntimeError(
                f"Turn latency {elapsed:.3f}s exceeded max {max_s:.3f}s. "
                "Tune REALTIME_TRANSCRIPT_DEBOUNCE_S / REALTIME_TRANSCRIPT_POST_SILENCE_S."
            )


async def _run(args: argparse.Namespace) -> int:
    scenarios = {args.scenario}
    if args.scenario == "all":
        scenarios = {"session_options", "greeting_echo_filter", "turn_latency"}

    if "session_options" in scenarios:
        await _scenario_session_options()
        print("OK: session_options")

    if "greeting_echo_filter" in scenarios:
        await _scenario_greeting_echo_filter()
        print("OK: greeting_echo_filter")

    if "turn_latency" in scenarios:
        await _scenario_turn_latency(max_s=float(args.turn_latency_max_s))
        print("OK: turn_latency")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local smoke tests for OpenAI Realtime voice behavior (no mic, no LiveKit rooms)."
    )
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "session_options", "greeting_echo_filter", "turn_latency"],
        help="Which smoke scenario to run (default: all).",
    )
    parser.add_argument(
        "--turn-latency-max-s",
        default="0.55",
        help="Max allowed transcript->reply latency for the turn_latency scenario (seconds).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

