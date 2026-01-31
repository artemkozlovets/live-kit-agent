#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import random
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from livekit import rtc


def _load_livekit_agent_id(*, repo_root: Path) -> str:
    livekit_toml = repo_root / "livekit.toml"
    if not livekit_toml.exists():
        raise RuntimeError(f"Missing {livekit_toml}")

    import tomllib  # py3.11+

    data = tomllib.load(livekit_toml.open("rb"))
    agent = data.get("agent")
    if not isinstance(agent, dict):
        raise RuntimeError("Invalid livekit.toml: missing [agent] section")

    agent_id = agent.get("id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise RuntimeError("Invalid livekit.toml: missing [agent].id")

    return agent_id.strip()


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _capture(cmd: list[str]) -> str:
    # Important: used for `lk token create`, whose output includes a token.
    # Never print the captured output.
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.stdout


def _parse_lk_token_output(output: str) -> tuple[str, str]:
    project_url: str | None = None
    access_token: str | None = None
    for line in output.splitlines():
        if line.startswith("Project URL:"):
            project_url = line.split(":", 1)[1].strip()
        elif line.startswith("Access token:"):
            access_token = line.split(":", 1)[1].strip()

    if not project_url or not access_token:
        raise RuntimeError("Failed to parse `lk token create` output (missing Project URL / Access token).")
    return project_url, access_token


async def _send_text_turn(*, livekit_url: str, token: str, topic: str, message: str, hold_open_s: float) -> None:
    room = rtc.Room()
    await room.connect(livekit_url, token)
    try:
        await room.local_participant.send_text(message, topic=topic)
        await asyncio.sleep(hold_open_s)
    finally:
        await room.disconnect()


class _AgentLogWaiter:
    def __init__(self, *, room_name: str, timeout_s: float) -> None:
        self._room_name = room_name
        self._timeout_s = timeout_s
        self._found = threading.Event()
        self._lines: deque[str] = deque(maxlen=250)
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    @property
    def found(self) -> bool:
        return self._found.is_set()

    def recent_lines(self) -> list[str]:
        return list(self._lines)

    def start(self) -> None:
        proc = subprocess.Popen(
            ["lk", "agent", "logs", "--log-type", "deploy"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if proc.stdout is None:
            proc.terminate()
            raise RuntimeError("Failed to start `lk agent logs` (no stdout).")

        self._proc = proc
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)

        if self._thread is not None:
            self._thread.join(timeout=3)

    def wait(self) -> bool:
        return self._found.wait(self._timeout_s)

    def _run(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None

        deadline = time.time() + self._timeout_s
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            line = line.rstrip("\n")
            self._lines.append(line)

            # The agent logs backend tool success as:
            # - message: "VOICE_DEBUG backend_tool_ok"
            # - includes: call_id=<room name>
            if self._room_name in line and "backend_tool_ok" in line:
                self._found.set()
                return


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end smoke test: dispatch LiveKit Cloud agent, send a lk.chat text turn, "
            "and verify the agent successfully calls the Railway /tools backend."
        )
    )
    parser.add_argument(
        "--room",
        default="",
        help="Room name to use (default: auto-generated).",
    )
    parser.add_argument(
        "--identity",
        default="smoke_text_tester",
        help="Participant identity for the text sender.",
    )
    parser.add_argument(
        "--topic",
        default="lk.chat",
        help="Text stream topic (default: lk.chat).",
    )
    parser.add_argument(
        "--message",
        default="My phone number is 305-555-0123. Please check my case status.",
        help="User message to send (default triggers validate_phone).",
    )
    parser.add_argument(
        "--agent-log-timeout-s",
        type=float,
        default=45.0,
        help="Seconds to wait for backend_tool_ok in agent logs.",
    )
    parser.add_argument(
        "--hold-open-s",
        type=float,
        default=3.0,
        help="Seconds to keep the participant connected after sending the message.",
    )
    parser.add_argument(
        "--keep-room",
        action="store_true",
        help="Do not delete the room on success (useful for debugging).",
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    repo_root = Path(__file__).resolve().parents[1]
    agent_id = _load_livekit_agent_id(repo_root=repo_root)

    room_name = args.room.strip()
    if not room_name:
        room_name = f"smoke-text-{time.strftime('%Y%m%d-%H%M%S')}-{random.randint(1000,9999)}"

    print(f"Room: {room_name}")
    print(f"Agent: {agent_id}")

    print("Creating room…")
    _run(["lk", "room", "create", "--empty-timeout", "300", room_name])

    print("Dispatching agent…")
    _run(["lk", "dispatch", "create", "--room", room_name, "--agent-name", agent_id])

    print("Creating participant token (not printed)…")
    token_out = _capture(
        [
            "lk",
            "token",
            "create",
            "--join",
            "--room",
            room_name,
            "--identity",
            args.identity,
            "--valid-for",
            "10m",
        ]
    )
    livekit_url, token = _parse_lk_token_output(token_out)

    waiter = _AgentLogWaiter(room_name=room_name, timeout_s=args.agent_log_timeout_s)
    waiter.start()

    try:
        print(f"Sending text to topic {args.topic!r}…")
        asyncio.run(
            _send_text_turn(
                livekit_url=livekit_url,
                token=token,
                topic=args.topic,
                message=args.message,
                hold_open_s=args.hold_open_s,
            )
        )

        print("Waiting for agent to call backend (/tools)…")
        ok = waiter.wait()
        if not ok:
            print("")
            print("ERROR: Did not see `backend_tool_ok` for this room in `lk agent logs`.")
            print("Recent agent logs (tail):")
            for line in waiter.recent_lines()[-60:]:
                print(line)
            print("")
            print("Debug tips:")
            print(f"  - Tail agent logs: lk agent logs --log-type deploy | rg {room_name!r}")
            print(f"  - Check participants: lk room participants list {room_name!r}")
            print("  - Verify Railway backend health: curl -sS https://<railway-domain>/health")
            return 1

        print("OK: saw `backend_tool_ok` in agent logs (LiveKit → agent → Railway /tools).")
    finally:
        waiter.stop()

    if args.keep_room:
        print("Keeping room (per --keep-room).")
    else:
        print("Deleting room…")
        _run(["lk", "room", "delete", room_name])

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
