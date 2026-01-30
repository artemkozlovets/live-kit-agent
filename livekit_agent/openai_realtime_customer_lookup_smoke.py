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
from livekit_agent.backend_tools_client import (  # noqa: E402
    BackendToolsClient,
    BackendToolsClientError,
)
from livekit_agent.openai_realtime_session import build_openai_realtime_session  # noqa: E402


DEFAULT_BACKEND_TOOLS_URL = "https://call-agent-development.up.railway.app/tools"


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Expected a boolean value, got: {value!r}")


def _default_run_dir() -> Path:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    # Reason: Keep smoke artifacts under the same `local-observability/run-*` pattern used elsewhere
    # so they stay out of git status by default (see `.gitignore`).
    return Path("local-observability") / f"run-{run_id}-openai-realtime-customer-lookup-smoke"


async def _lookup_customer(
    *,
    backend: BackendToolsClient,
    call_id: str,
    phone_number: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_phone = await backend.call_tool(
        call_id=call_id,
        sip_phone_number=None,
        confirmed_callback_number=None,
        assistant_variable_values=None,
        tool_call_id=f"smoke-validate-phone-{int(time.time() * 1000)}",
        tool_name="validate_phone",
        tool_arguments={"phone_number": phone_number},
    )

    formatted = validate_phone.get("formatted") if isinstance(validate_phone, dict) else None
    if isinstance(formatted, str) and formatted.strip():
        lookup_number = formatted.strip()
    else:
        proceed_unvalidated = (
            validate_phone.get("proceed_unvalidated") if isinstance(validate_phone, dict) else None
        )
        if proceed_unvalidated is True:
            lookup_number = phone_number
        else:
            raise RuntimeError(f"validate_phone did not return a usable phone number: {validate_phone}")

    check_customer = await backend.call_tool(
        call_id=call_id,
        sip_phone_number=None,
        confirmed_callback_number=lookup_number,
        assistant_variable_values=None,
        tool_call_id=f"smoke-check-customer-{int(time.time() * 1000)}",
        tool_name="check_customer",
        tool_arguments={"phone_number": lookup_number},
    )

    return validate_phone, check_customer


async def _run(args: argparse.Namespace) -> int:
    backend_tools_url = (
        args.backend_tools_url or os.environ.get("BACKEND_TOOLS_URL") or DEFAULT_BACKEND_TOOLS_URL
    ).strip()
    if not backend_tools_url:
        raise RuntimeError("BACKEND_TOOLS_URL is required (must end with /tools).")

    expected_found = _parse_bool(args.expect_found)

    run_dir = Path(args.out_dir) if args.out_dir else _default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    backend = BackendToolsClient(
        tools_url=backend_tools_url,
        tools_token=(args.tools_token or os.environ.get("TOOLS_TOKEN")),
        timeout_s=float(args.backend_timeout_s),
    )

    # 1) Deterministic backend check (validate_phone -> check_customer)
    try:
        validate_phone, check_customer = await _lookup_customer(
            backend=backend,
            call_id=args.call_id,
            phone_number=args.phone_number,
        )
    except BackendToolsClientError as exc:
        payload = {"ok": False, "error": str(exc)}
        (run_dir / "result.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        raise

    (run_dir / "validate_phone.json").write_text(
        json.dumps(validate_phone, indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "check_customer.json").write_text(
        json.dumps(check_customer, indent=2, sort_keys=True), encoding="utf-8"
    )

    found = bool(check_customer.get("found") is True) if isinstance(check_customer, dict) else False
    customer = check_customer.get("customer") if isinstance(check_customer, dict) else None

    ok = found is expected_found
    result_payload = {
        "ok": ok,
        "expected_found": expected_found,
        "found": found,
        "customer": customer,
    }
    (run_dir / "result.json").write_text(
        json.dumps(result_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    # 2) OpenAI Realtime audio output (no mic): speak a short summary, capture WAV.
    if _parse_bool(args.with_audio):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required when --with-audio=true.")

        voice = (args.voice or "").strip() or None
        audio_path = run_dir / "assistant.wav"

        wav_out = WavFileAudioOutput(path=audio_path)
        llm_to_close: Any = None
        try:
            async with build_openai_realtime_session(modalities=["text", "audio"], voice=voice) as session:
                llm_to_close = session.llm
                session.output.audio = wav_out

                agent = Agent(
                    instructions=(
                        "You are running inside an automated smoke test.\n"
                        "Speak a short, clear response.\n"
                        "Avoid markdown.\n"
                    )
                )
                await session.start(agent, record=False)

                if found:
                    prompt = (
                        "Please say: 'Thanks — I found your account using your phone number. "
                        "How can I help you today?'"
                    )
                else:
                    prompt = (
                        "Please say: 'Thanks — I could not find an account for that phone number. "
                        "Could you repeat the full 10-digit number including the area code?'"
                    )

                handle = session.generate_reply(user_input=prompt)
                await asyncio.wait_for(handle.wait_for_playout(), timeout=float(args.audio_timeout_s))
        finally:
            wav_out.close()
            aclose = getattr(llm_to_close, "aclose", None)
            if callable(aclose):
                res = aclose()
                if asyncio.iscoroutine(res):
                    await res

    print(f"Run dir: {run_dir}")
    print(f"Backend: validate_phone -> check_customer (found={found})")
    if _parse_bool(args.with_audio):
        print(f"Audio:   {run_dir / 'assistant.wav'}")

    return 0 if ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAI Realtime + backend DB lookup smoke test (no microphone)."
    )
    parser.add_argument("--phone-number", required=True, help="Phone number (any formatting is OK).")
    parser.add_argument("--call-id", default="smoke-customer-lookup", help="Call correlation ID.")
    parser.add_argument("--backend-tools-url", default=None, help="Overrides BACKEND_TOOLS_URL.")
    parser.add_argument("--tools-token", default=None, help="Overrides TOOLS_TOKEN.")
    parser.add_argument("--backend-timeout-s", default="30", help="Backend timeout in seconds (default: 30).")

    parser.add_argument(
        "--expect-found",
        default="true",
        help="If true, exits non-zero when the customer is not found (default: true).",
    )

    parser.add_argument(
        "--with-audio",
        default="true",
        help="If true, also generates assistant audio via OpenAI Realtime and saves assistant.wav (default: true).",
    )
    parser.add_argument("--voice", default=os.environ.get("OPENAI_REALTIME_VOICE"), help="Voice name.")
    parser.add_argument("--audio-timeout-s", default="60", help="Audio generation timeout (default: 60).")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: timestamped under local-observability/).")

    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
