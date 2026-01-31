#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import ast
import json
import os
import random
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from livekit import rtc

DEFAULT_REPORTS_URL = "https://call-agent-development.up.railway.app/observability/session-report"
DEFAULT_AUDIO_SAMPLE_URL = "https://upload.wikimedia.org/wikipedia/commons/9/96/Speech_12dB_opus_7kbps.opus"


def _now_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _default_run_dir(*, run_id: str) -> Path:
    # Reason: keep smoke artifacts under local-observability (ignored by default).
    return Path("local-observability") / f"run-{run_id}-livekit-cloud-smoke"


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
    # Important: `lk token create` output includes a token, so never print it.
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


async def _send_text_turns(
    *,
    livekit_url: str,
    token: str,
    topic: str,
    messages: list[str],
    between_turn_s: float,
    hold_open_s: float,
) -> None:
    room = rtc.Room()
    await room.connect(livekit_url, token)
    try:
        for idx, message in enumerate(messages):
            await room.local_participant.send_text(message, topic=topic)
            if idx < len(messages) - 1:
                await asyncio.sleep(between_turn_s)
        await asyncio.sleep(hold_open_s)
    finally:
        await room.disconnect()


def _download_file(*, url: str, path: Path, timeout_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        request = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                # Reason: some hosts (ex: Wikimedia) reject requests without a User-Agent.
                "User-Agent": "livekit-cloud-smoke/1.0",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            body = resp.read()
    except urllib.error.URLError:
        # Fall back to curl (more likely to pass host anti-bot filtering).
        subprocess.run(["curl", "-L", "-sS", "-o", str(path), url], check=True)
        body = path.read_bytes()

    if not body:
        raise RuntimeError(f"Downloaded empty body from {url}")

    path.write_bytes(body)


def _ensure_audio_fixture(*, url: str, path: Path, timeout_s: float) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    _download_file(url=url, path=path, timeout_s=timeout_s)
    return path


def _transcode_opus_with_tail_silence(*, src_path: Path, dst_path: Path, silence_s: float) -> None:
    # Lazy import so text-only smokes don't pay the import cost.
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: PyAV (`av`). Install it with `pip install av` "
            "(or reinstall this repo's requirements)."
        ) from exc

    if silence_s <= 0:
        dst_path.write_bytes(src_path.read_bytes())
        return

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if dst_path.exists():
        dst_path.unlink()

    in_container = av.open(str(src_path))
    try:
        in_audio = next((s for s in in_container.streams if s.type == "audio"), None)
        if in_audio is None:
            raise RuntimeError(f"No audio stream found in {src_path}")

        out_container = av.open(str(dst_path), mode="w", format="ogg")
        try:
            # Prefer libopus but fall back to opus if needed.
            try:
                out_stream = out_container.add_stream("libopus", rate=48000)
            except Exception:
                out_stream = out_container.add_stream("opus", rate=48000)

            resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=48000)

            for packet in in_container.demux(in_audio):
                for frame in packet.decode():
                    for out_frame in resampler.resample(frame):
                        for out_packet in out_stream.encode(out_frame):
                            out_container.mux(out_packet)

            total_silence_samples = int(silence_s * 48000)
            silence_frame_samples = 960  # 20ms at 48kHz (common Opus frame size)
            remaining = total_silence_samples
            while remaining > 0:
                n = min(silence_frame_samples, remaining)
                silence = av.AudioFrame(format="s16", layout="mono", samples=n)
                silence.sample_rate = 48000
                for plane in silence.planes:
                    plane.update(b"\x00" * plane.buffer_size)

                for out_packet in out_stream.encode(silence):
                    out_container.mux(out_packet)
                remaining -= n

            for out_packet in out_stream.encode(None):
                out_container.mux(out_packet)
        finally:
            out_container.close()
    finally:
        in_container.close()


def _ensure_audio_fixture_with_tail_silence(
    *, url: str, path: Path, tail_silence_s: float, timeout_s: float
) -> Path:
    base_path = path.with_suffix(".base.opus")
    _ensure_audio_fixture(url=url, path=base_path, timeout_s=timeout_s)

    if path.exists() and path.stat().st_size > 0:
        return path

    _transcode_opus_with_tail_silence(src_path=base_path, dst_path=path, silence_s=tail_silence_s)
    return path


def _url_join(*, base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _http_get_json(*, url: str, token: str | None, timeout_s: float) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url=url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET failed: {url}: {exc}") from exc

    if not body.strip():
        return status, {}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return status, {}

    return status, payload if isinstance(payload, dict) else {}


def _poll_session_report(
    *,
    reports_url: str,
    reports_token: str | None,
    room_name: str,
    timeout_s: float,
    poll_every_s: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    report_url = _url_join(base=reports_url, path=urllib.parse.quote(room_name, safe=""))
    last_status: int | None = None
    while time.time() < deadline:
        status, payload = _http_get_json(url=report_url, token=reports_token, timeout_s=10.0)
        last_status = status
        if status == 200 and payload:
            return payload
        if status in {401, 403}:
            raise RuntimeError(
                "Session report endpoint is protected. Set SESSION_REPORTS_TOKEN in your shell "
                "(or pass --reports-token) to fetch reports."
            )
        time.sleep(poll_every_s)

    raise TimeoutError(f"Timed out waiting for session report (last status={last_status}) url={report_url}")


def _iter_events(report_payload: dict[str, Any]) -> list[dict[str, Any]]:
    report = report_payload.get("report")
    if not isinstance(report, dict):
        return []
    events = report.get("events")
    return events if isinstance(events, list) else []


def _event_created_at(ev: dict[str, Any]) -> float:
    created_at = ev.get("created_at")
    return float(created_at) if isinstance(created_at, (int, float)) else 0.0


def _find_last_final_transcript(events: list[dict[str, Any]]) -> tuple[float, str]:
    best_ts = 0.0
    best_text = ""
    for ev in events:
        if ev.get("type") != "user_input_transcribed":
            continue
        if ev.get("is_final") is not True:
            continue
        transcript = ev.get("transcript")
        if not isinstance(transcript, str):
            continue
        transcript = transcript.strip()
        if not transcript:
            continue
        ts = _event_created_at(ev)
        if ts >= best_ts:
            best_ts = ts
            best_text = transcript
    return best_ts, best_text


def _find_user_message_timestamp(events: list[dict[str, Any]], *, contains: str) -> float:
    needle = contains.strip()
    if not needle:
        return 0.0

    for ev in events:
        if ev.get("type") != "conversation_item_added":
            continue
        item = ev.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        joined = " ".join(str(c) for c in content if isinstance(c, str)).strip()
        if not joined:
            continue
        if needle in joined:
            return _event_created_at(ev) or float(item.get("created_at") or 0.0)

    return 0.0


def _has_assistant_message_after(events: list[dict[str, Any]], *, after_ts: float) -> bool:
    for ev in events:
        if ev.get("type") != "conversation_item_added":
            continue
        ev_ts = _event_created_at(ev)
        if ev_ts <= after_ts:
            continue
        item = ev.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        if isinstance(content, list) and any(isinstance(c, str) and c.strip() for c in content):
            return True
    return False


def _parse_tool_output(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}

    raw = value.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    # Session reports may store tool outputs as Python dict strings (single quotes).
    try:
        parsed = ast.literal_eval(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _find_last_tool_output(events: list[dict[str, Any]], *, tool_name: str) -> tuple[float, dict[str, Any]]:
    best_ts = 0.0
    best_payload: dict[str, Any] = {}
    for ev in events:
        if ev.get("type") != "function_tools_executed":
            continue
        outputs = ev.get("function_call_outputs")
        if not isinstance(outputs, list):
            continue
        for out in outputs:
            if not isinstance(out, dict):
                continue
            if out.get("name") != tool_name:
                continue
            ts = _event_created_at(ev)
            payload = _parse_tool_output(out.get("output"))
            if ts >= best_ts:
                best_ts = ts
                best_payload = payload
    return best_ts, best_payload


def _run_lk_room_join_publish(
    *,
    room_name: str,
    identity: str,
    publish_path: Path,
    hold_open_s: float,
    exit_after_publish: bool,
    log_path: Path | None = None,
) -> None:
    cmd = [
        "lk",
        "room",
        "join",
        room_name,
        "--identity",
        identity,
        "--publish",
        str(publish_path),
        "--auto-subscribe",
    ]
    if exit_after_publish:
        cmd.append("--exit-after-publish")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")
    else:
        log_file = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file or subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            proc.wait(timeout=hold_open_s)
        except subprocess.TimeoutExpired:
            # Reason: keep the smoke deterministic; we only need to publish and wait a bit for the agent.
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        # Exit code is not reliable here (SIGINT etc.), but we still want failures to surface.
        if proc.returncode not in {0, 130, -signal.SIGINT}:
            out = ""
            if log_path is not None and log_path.exists():
                out = log_path.read_text(encoding="utf-8", errors="replace")
            elif proc.stdout is not None:
                out = proc.stdout.read() or ""
            raise RuntimeError(f"`lk room join` failed (code={proc.returncode}). Output:\n{out}")
    finally:
        if log_file is not None:
            log_file.close()


@dataclass(frozen=True)
class _ScenarioResult:
    ok: bool
    reason: str
    room_name: str
    report_url: str


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _scenario_text_reply(
    *,
    agent_id: str,
    reports_url: str,
    reports_token: str | None,
    run_dir: Path,
    room_name: str,
    topic: str,
    identity: str,
    message: str,
    text_hold_open_s: float,
    agent_startup_wait_s: float,
    post_turn_wait_s: float,
    report_timeout_s: float,
    keep_room: bool,
) -> _ScenarioResult:
    print(f"[text] Room: {room_name}")
    print(f"[text] Agent: {agent_id}")

    try:
        _run(["lk", "room", "create", "--empty-timeout", "300", room_name])
        _run(["lk", "dispatch", "create", "--room", room_name, "--agent-name", agent_id])
        if agent_startup_wait_s > 0:
            time.sleep(agent_startup_wait_s)

        token_out = _capture(
            [
                "lk",
                "token",
                "create",
                "--join",
                "--room",
                room_name,
                "--identity",
                identity,
                "--valid-for",
                "10m",
            ]
        )
        livekit_url, token = _parse_lk_token_output(token_out)

        asyncio.run(
            _send_text_turn(
                livekit_url=livekit_url,
                token=token,
                topic=topic,
                message=message,
                hold_open_s=text_hold_open_s,
            )
        )

        if post_turn_wait_s > 0:
            time.sleep(post_turn_wait_s)
    finally:
        if not keep_room:
            subprocess.run(["lk", "room", "delete", room_name], check=False)

    report = _poll_session_report(
        reports_url=reports_url,
        reports_token=reports_token,
        room_name=room_name,
        timeout_s=report_timeout_s,
        poll_every_s=1.0,
    )

    report_path = run_dir / "text" / "session_report.json"
    _write_json(report_path, report)

    events = _iter_events(report)
    user_ts = _find_user_message_timestamp(events, contains=message)
    if user_ts <= 0:
        return _ScenarioResult(
            ok=False,
            reason="did_not_find_user_message_in_report",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    if not _has_assistant_message_after(events, after_ts=user_ts):
        return _ScenarioResult(
            ok=False,
            reason="no_assistant_reply_after_user_message",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    return _ScenarioResult(
        ok=True,
        reason="ok",
        room_name=room_name,
        report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
    )


def _scenario_audio_reply(
    *,
    agent_id: str,
    reports_url: str,
    reports_token: str | None,
    run_dir: Path,
    room_name: str,
    identity: str,
    audio_sample_url: str,
    audio_hold_open_s: float,
    agent_startup_wait_s: float,
    post_turn_wait_s: float,
    report_timeout_s: float,
    keep_room: bool,
) -> _ScenarioResult:
    print(f"[audio] Room: {room_name}")
    print(f"[audio] Agent: {agent_id}")

    try:
        _run(["lk", "room", "create", "--empty-timeout", "300", room_name])
        _run(["lk", "dispatch", "create", "--room", room_name, "--agent-name", agent_id])
        if agent_startup_wait_s > 0:
            time.sleep(agent_startup_wait_s)

        fixture_path = Path("/tmp/livekit-cloud-smoke-speech-with-tail-silence.ogg")
        _ensure_audio_fixture_with_tail_silence(
            url=audio_sample_url,
            path=fixture_path,
            tail_silence_s=2.0,
            timeout_s=30.0,
        )

        _run_lk_room_join_publish(
            room_name=room_name,
            identity=identity,
            publish_path=fixture_path,
            hold_open_s=audio_hold_open_s,
            exit_after_publish=False,
            log_path=run_dir / "audio" / "lk_room_join.log",
        )
        if post_turn_wait_s > 0:
            time.sleep(post_turn_wait_s)
    finally:
        if not keep_room:
            subprocess.run(["lk", "room", "delete", room_name], check=False)

    report = _poll_session_report(
        reports_url=reports_url,
        reports_token=reports_token,
        room_name=room_name,
        timeout_s=report_timeout_s,
        poll_every_s=1.0,
    )

    report_path = run_dir / "audio" / "session_report.json"
    _write_json(report_path, report)

    events = _iter_events(report)
    ts, transcript = _find_last_final_transcript(events)
    if ts <= 0 or not transcript:
        return _ScenarioResult(
            ok=False,
            reason="did_not_find_final_transcript",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    if not _has_assistant_message_after(events, after_ts=ts):
        return _ScenarioResult(
            ok=False,
            reason="no_assistant_reply_after_transcript",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    return _ScenarioResult(
        ok=True,
        reason=f"ok (transcript={transcript!r})",
        room_name=room_name,
        report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
    )


def _scenario_transfer_to_human(
    *,
    agent_id: str,
    reports_url: str,
    reports_token: str | None,
    run_dir: Path,
    room_name: str,
    topic: str,
    identity: str,
    turns: list[str],
    between_turn_s: float,
    hold_open_s: float,
    agent_startup_wait_s: float,
    post_turn_wait_s: float,
    report_timeout_s: float,
    keep_room: bool,
    expect: str,
) -> _ScenarioResult:
    print(f"[transfer] Room: {room_name}")
    print(f"[transfer] Agent: {agent_id}")

    turns = [t.strip() for t in turns if t.strip()]
    if not turns:
        turns = [
            "I'm really frustrated. This isn't working. I want to talk to a human.",
            "Yes, please connect me to a human agent now.",
        ]

    try:
        _run(["lk", "room", "create", "--empty-timeout", "300", room_name])
        _run(["lk", "dispatch", "create", "--room", room_name, "--agent-name", agent_id])
        if agent_startup_wait_s > 0:
            time.sleep(agent_startup_wait_s)

        token_out = _capture(
            [
                "lk",
                "token",
                "create",
                "--join",
                "--room",
                room_name,
                "--identity",
                identity,
                "--valid-for",
                "10m",
            ]
        )
        livekit_url, token = _parse_lk_token_output(token_out)

        asyncio.run(
            _send_text_turns(
                livekit_url=livekit_url,
                token=token,
                topic=topic,
                messages=turns,
                between_turn_s=between_turn_s,
                hold_open_s=hold_open_s,
            )
        )

        if post_turn_wait_s > 0:
            time.sleep(post_turn_wait_s)
    finally:
        if not keep_room:
            subprocess.run(["lk", "room", "delete", room_name], check=False)

    report = _poll_session_report(
        reports_url=reports_url,
        reports_token=reports_token,
        room_name=room_name,
        timeout_s=report_timeout_s,
        poll_every_s=1.0,
    )

    report_path = run_dir / "transfer" / "session_report.json"
    _write_json(report_path, report)

    events = _iter_events(report)
    ts, payload = _find_last_tool_output(events, tool_name="transfer_to_human")
    if ts <= 0 or not payload:
        return _ScenarioResult(
            ok=False,
            reason="did_not_call_transfer_to_human",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    ok_value = payload.get("ok")
    is_ok = ok_value is True
    if expect == "ok":
        if is_ok:
            return _ScenarioResult(
                ok=True,
                reason="ok",
                room_name=room_name,
                report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
            )
        code = ((payload.get("error") or {}) if isinstance(payload.get("error"), dict) else {}).get("code")
        return _ScenarioResult(
            ok=False,
            reason=f"transfer_expected_ok_got_error:{code}",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    if is_ok:
        return _ScenarioResult(
            ok=False,
            reason="transfer_unexpected_success",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    error = payload.get("error")
    if not isinstance(error, dict):
        return _ScenarioResult(
            ok=False,
            reason="transfer_missing_error",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    code = error.get("code")
    if code != expect:
        return _ScenarioResult(
            ok=False,
            reason=f"transfer_unexpected_error_code:{code}",
            room_name=room_name,
            report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
        )

    return _ScenarioResult(
        ok=True,
        reason=f"ok (expected_error_code={expect})",
        room_name=room_name,
        report_url=_url_join(base=reports_url, path=urllib.parse.quote(room_name, safe="")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LiveKit Cloud smoke tests (no browser): create a room, dispatch the deployed agent, "
            "send text/publish audio/trigger transfer, then assert on the session report."
        )
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario(s) to run: text, audio, transfer (default: text+audio).",
    )
    parser.add_argument("--reports-url", default=os.environ.get("SESSION_REPORTS_URL") or DEFAULT_REPORTS_URL)
    parser.add_argument("--reports-token", default=os.environ.get("SESSION_REPORTS_TOKEN") or "")

    parser.add_argument("--topic", default="lk.chat", help="Text topic for the text scenario.")
    parser.add_argument("--text-identity", default="smoke_text_tester", help="Identity for text participant.")
    parser.add_argument("--text-message", default="Hello from cloud text smoke.", help="User text to send.")
    parser.add_argument("--text-hold-open-s", type=float, default=3.0, help="Seconds to keep text sender connected.")
    parser.add_argument(
        "--agent-startup-wait-s",
        type=float,
        default=2.0,
        help="Seconds to wait after dispatch before sending input (default: 2).",
    )
    parser.add_argument(
        "--post-turn-wait-s",
        type=float,
        default=6.0,
        help="Seconds to wait after sending input before deleting the room (default: 6).",
    )

    parser.add_argument("--audio-identity", default="smoke_audio_tester", help="Identity for audio publisher.")
    parser.add_argument("--audio-sample-url", default=DEFAULT_AUDIO_SAMPLE_URL, help="URL for Ogg Opus audio fixture.")
    parser.add_argument("--audio-hold-open-s", type=float, default=20.0, help="Seconds to keep publisher connected.")

    parser.add_argument("--transfer-identity", default="smoke_transfer_tester", help="Identity for transfer participant.")
    parser.add_argument(
        "--transfer-turn",
        action="append",
        default=[],
        help="User turn text for transfer scenario (repeatable).",
    )
    parser.add_argument(
        "--transfer-between-turn-s",
        type=float,
        default=2.0,
        help="Seconds to wait between transfer turns (default: 2).",
    )
    parser.add_argument(
        "--transfer-hold-open-s",
        type=float,
        default=10.0,
        help="Seconds to keep transfer sender connected after the last turn (default: 10).",
    )
    parser.add_argument(
        "--transfer-expect",
        default="no_sip_participant",
        help=(
            "Expected transfer outcome: 'ok' or an error code (default: no_sip_participant). "
            "In real telephony calls on LiveKit Phone Numbers, this is typically 'transfer_not_supported'."
        ),
    )

    parser.add_argument("--report-timeout-s", type=float, default=90.0, help="Seconds to wait for session report.")
    parser.add_argument("--keep-room", action="store_true", help="Do not delete rooms on exit (debug).")
    args = parser.parse_args()

    scenarios = [s.strip().lower() for s in args.scenario if s.strip()]
    if not scenarios:
        scenarios = ["text", "audio"]

    reports_url = str(args.reports_url or "").strip()
    if not reports_url:
        print("ERROR: missing reports URL. Set SESSION_REPORTS_URL or pass --reports-url.", file=sys.stderr)
        return 2

    reports_token = str(args.reports_token or "").strip() or None

    repo_root = Path(__file__).resolve().parents[1]
    agent_id = _load_livekit_agent_id(repo_root=repo_root)
    run_id = _now_run_id()
    run_dir = _default_run_dir(run_id=run_id)

    results: list[_ScenarioResult] = []
    try:
        for scenario in scenarios:
            room_name = f"smoke-cloud-{scenario}-{run_id}-{random.randint(1000,9999)}"
            if scenario == "text":
                results.append(
                    _scenario_text_reply(
                        agent_id=agent_id,
                        reports_url=reports_url,
                        reports_token=reports_token,
                        run_dir=run_dir,
                        room_name=room_name,
                        topic=str(args.topic),
                        identity=str(args.text_identity),
                        message=str(args.text_message),
                        text_hold_open_s=float(args.text_hold_open_s),
                        agent_startup_wait_s=float(args.agent_startup_wait_s),
                        post_turn_wait_s=float(args.post_turn_wait_s),
                        report_timeout_s=float(args.report_timeout_s),
                        keep_room=bool(args.keep_room),
                    )
                )
            elif scenario == "audio":
                results.append(
                    _scenario_audio_reply(
                        agent_id=agent_id,
                        reports_url=reports_url,
                        reports_token=reports_token,
                        run_dir=run_dir,
                        room_name=room_name,
                        identity=str(args.audio_identity),
                        audio_sample_url=str(args.audio_sample_url),
                        audio_hold_open_s=float(args.audio_hold_open_s),
                        agent_startup_wait_s=float(args.agent_startup_wait_s),
                        post_turn_wait_s=float(args.post_turn_wait_s),
                        report_timeout_s=float(args.report_timeout_s),
                        keep_room=bool(args.keep_room),
                    )
                )
            elif scenario == "transfer":
                results.append(
                    _scenario_transfer_to_human(
                        agent_id=agent_id,
                        reports_url=reports_url,
                        reports_token=reports_token,
                        run_dir=run_dir,
                        room_name=room_name,
                        topic=str(args.topic),
                        identity=str(args.transfer_identity),
                        turns=[str(t) for t in args.transfer_turn],
                        between_turn_s=float(args.transfer_between_turn_s),
                        hold_open_s=float(args.transfer_hold_open_s),
                        agent_startup_wait_s=float(args.agent_startup_wait_s),
                        post_turn_wait_s=float(args.post_turn_wait_s),
                        report_timeout_s=float(args.report_timeout_s),
                        keep_room=bool(args.keep_room),
                        expect=str(args.transfer_expect).strip(),
                    )
                )
            else:
                print(f"ERROR: unknown scenario: {scenario!r}", file=sys.stderr)
                return 2
    except Exception as exc:
        (run_dir / "result.json").parent.mkdir(parents=True, exist_ok=True)
        _write_json(
            run_dir / "result.json",
            {"ok": False, "error": str(exc), "scenarios": scenarios},
        )
        raise

    payload = {
        "ok": all(r.ok for r in results),
        "scenarios": [
            {"scenario": s, "ok": r.ok, "reason": r.reason, "room_name": r.room_name, "report_url": r.report_url}
            for s, r in zip(scenarios, results)
        ],
    }
    _write_json(run_dir / "result.json", payload)

    for s, r in zip(scenarios, results):
        status = "OK" if r.ok else "FAIL"
        print(f"[{status}] {s}: {r.reason} (room={r.room_name})")

    print(f"Artifacts: {run_dir}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
