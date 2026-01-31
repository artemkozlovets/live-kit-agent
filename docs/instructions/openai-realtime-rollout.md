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

## 4) LiveKit Cloud end-to-end smoke (no browser, text-mode)
This is the fastest remote “is everything wired up?” check because it avoids audio
encoding / transcription edge cases.

Big picture:
- Dispatches the deployed LiveKit Cloud agent into a new room
- Joins as a normal participant
- Sends a text message on the `lk.chat` text stream topic (LiveKit text streams)
- Verifies the agent successfully calls the Railway `POST /tools` backend by watching
  `lk agent logs` for a `backend_tool_ok` entry for that room

Run:
```bash
./scripts/run_livekit_cloud_text_smoke.sh
```

What it does / doesn’t prove:
- ✅ Dispatch + agent startup works
- ✅ Agent receives `lk.chat` text input
- ✅ Agent can reach the Railway `POST /tools` backend (auth + networking)
- ❌ Does *not* validate audio input (mic/VAD/transcription) or audio output (TTS playback)

Note: the script deletes the room on success; pass `--keep-room` to keep it around for debugging.

Expected:
- Exit code `0`
- Output includes `OK: saw backend_tool_ok in agent logs`

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
