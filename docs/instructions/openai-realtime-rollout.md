# OpenAI Realtime Rollout (Smoke Checklist)

Last updated: 2026-01-31

## Big picture
This repo runs:
- a **LiveKit agent** that uses **OpenAI Realtime** by default, and
- a **FastAPI tools backend** that exposes `POST /tools` (v2) with auth.

This runbook is the smallest checklist to prove the stack is healthy end-to-end.

## Preconditions (must be true)
- Backend has `TOOLS_TOKEN` set (agent ↔ backend shared secret).
- Agent has `OPENAI_API_KEY`, `BACKEND_TOOLS_URL` (ends with `/tools`), and `TOOLS_TOKEN` set.
- You’re authenticated to the correct LiveKit Cloud account: `lk cloud auth`
- This repo points at the intended LiveKit project/agent: `cat livekit.toml`
- Optional: set `AGENT_BACKEND_GUARDRAILS=false` to run an **OpenAI-first** flow (no `get_case_status` call each turn).
- Optional but recommended: session report pipeline configured (see `docs/documentations/debug.md`).

## 1) Backend smoke: `/tools` works + auth enforced

### Happy path (200 + results shape)
```bash
curl -sS -X POST "http://127.0.0.1:8000/tools" \
  -H "Content-Type: application/json" \
  -H "X-TOOLS-TOKEN: dev-secret" \
  -d '{"call":{"id":"room-123"},"tool_calls":[{"id":"tc-1","name":"validate_phone","arguments":{"phone_number":"+15551234567"}}]}'
```

Expected:
- HTTP `200`
- JSON with `results[0].tool_call_id == "tc-1"` and `results[0].ok == true`

### Failure path (missing/invalid token → 401)
```bash
curl -sS -i -X POST "http://127.0.0.1:8000/tools" \
  -H "Content-Type: application/json" \
  -d '{"call":{"id":"room-123"},"tool_calls":[]}'
```

Expected: HTTP `401`.

## 2) Local audio smoke (fastest)
Runs backend + agent locally and captures artifacts:
```bash
./scripts/run_local_audio_console.sh
```

Talk through:
1) Info dump
2) Missing-field questions (only missing fields)
3) Summary + explicit “yes”
4) Booking succeeds

### No-mic OpenAI Realtime audio smoke (OpenAI-only)
Use this when you want to validate **“does OpenAI Realtime actually produce audio?”**
without mic permissions, LiveKit rooms, or the tools backend:

```bash
./scripts/run_openai_realtime_audio_smoke.sh \
  --turn "Please say: 'OpenAI realtime audio smoke test OK.'" \
  --modalities "text,audio"
```

Expected:
- `assistant.wav` exists and contains audible speech.

### No-network voice logic smoke (agent-only)
Use this when you want to validate **“do our Realtime turn hooks behave sanely?”**
without OpenAI network calls, mic permissions, or LiveKit rooms:

```bash
./scripts/run_openai_realtime_voice_smoke.sh
```

What it checks:
- The session defaults to buffering user audio during uninterruptible speech (`LK_DISCARD_AUDIO_IF_UNINTERRUPTIBLE=false`).
- The agent ignores a transcript that matches the phone greeting (helps prevent self-talk/echo loops).
- The transcript-driven turn loop triggers within a small latency budget (regression guard).

Scenarios:
- `session_options`: validates session defaults are safe for an uninterruptible greeting.
- `greeting_echo_filter`: simulates a greeting being transcribed as user input and ensures it’s ignored, then ensures a real user turn triggers the backend-first loop.
- `turn_latency`: measures transcript→reply trigger time and fails if it exceeds `--turn-latency-max-s` (default: `0.55`).

Expected output:
- `OK: session_options`
- `OK: greeting_echo_filter`
- `turn_latency_s=...`
- `OK: turn_latency`

What it does *not* prove:
- Real microphone audio, LiveKit transport timing, PSTN echo conditions, or “first words after greeting” in a real call.
- Use `./scripts/run_local_audio_console.sh`, LiveKit Cloud smoke, and/or a real phone call for those.

### No-mic customer lookup smoke (backend DB)
Use this when you want to validate **“does `check_customer` find the caller in the DB?”**
without mic permissions or LiveKit rooms:

```bash
./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "+1 (305) 555-0123" \
  --expect-found true
```

Expected:
- exit code `0`
- `check_customer.json` shows `"found": true`

## 3) Staging telephony smoke (high-signal)
- Place an inbound PSTN call and confirm:
  - a LiveKit room is created
  - agent joins the room
  - barge-in works (interruptions feel natural)
- Confirm booking safety:
  - if the caller never says an explicit “yes”, booking must not happen
  - if booking is attempted without confirmation, the backend should respond with `booking_not_confirmed`

Tip: correlate systems by **room name** (call_id).

## 4) LiveKit Cloud end-to-end smoke (no browser)
This is the “unit test for deployments” check:
- Runs against the **deployed** LiveKit Cloud agent via `lk` (no browser).
- Asserts on the backend **session report** (`/observability/session-report`) so we can validate turns deterministically.

Run:
```bash
# text turn → assistant reply
./scripts/run_livekit_cloud_smoke.sh --scenario text

# publish audio → final transcript → assistant reply
./scripts/run_livekit_cloud_smoke.sh --scenario audio

# both (default)
./scripts/run_livekit_cloud_smoke.sh
```

What it does / doesn’t prove:
- ✅ Dispatch + agent startup works
- ✅ Agent receives text input and replies
- ✅ Agent receives audio input, produces a final transcript, and replies
- ✅ Session report exporter pipeline works (agent → backend)
- ❌ Does *not* validate PSTN routing / SIP trunk behavior (use the telephony smoke step for that)

Expected:
- Exit code `0`
- Artifacts saved under `local-observability/run-*-livekit-cloud-smoke/`

Fallback (older, log-based text smoke):
```bash
./scripts/run_livekit_cloud_text_smoke.sh
```

Use the fallback when session reports aren’t configured yet; it only proves dispatch + backend connectivity.

## Rollback (safety)
This repo is intentionally **OpenAI Realtime-only** (no legacy STT/TTS pipeline). If you need to roll back quickly:
- Disable dispatch / route calls away from the LiveKit agent temporarily.
- Redeploy the last-known-good agent version and/or backend version.

## Verification (repo-level)
- Full suite: `./scripts/test_all.sh`

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/documentations/debug.md`
