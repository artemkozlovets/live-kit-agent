# OpenAI Realtime Rollout (Smoke + Rollback)

Last updated: 2026-01-28

## Big picture
This repo runs:
- a **LiveKit agent** that uses **OpenAI Realtime** by default, and
- a **FastAPI tools backend** that exposes `POST /tools` (v2) with auth.

This runbook is the smallest checklist to prove the stack is healthy end-to-end, and to roll back safely if needed.

## Preconditions (must be true)
- Backend has `TOOLS_TOKEN` set (agent ↔ backend shared secret).
- Agent has `OPENAI_API_KEY`, `BACKEND_TOOLS_URL` (ends with `/tools`), and `TOOLS_TOKEN` set.
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

## 3) Staging telephony smoke (high-signal)
- Place an inbound PSTN call and confirm:
  - a LiveKit room is created
  - agent joins the room
  - barge-in works (interruptions feel natural)
- Confirm booking safety:
  - if the caller never says an explicit “yes”, booking must not happen
  - if booking is attempted without confirmation, the backend should respond with `booking_not_confirmed`

Tip: correlate systems by **room name** (call_id).

## Rollback (kill switch)
Set `AGENT_ENGINE=legacy` on the agent service to fall back to the previous Deepgram+Cartesia pipeline.

Notes:
- Legacy mode requires `DEEPGRAM_API_KEY` and `CARTESIA_API_KEY` (and optionally `GOOGLE_API_KEY`).
- `/vapi/tools` is removed (404); legacy mode still calls the `/tools` endpoint.

## Verification (repo-level)
- Full suite: `./scripts/test_all.sh`

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/documentations/debug.md`
- `docs/openai_realtime-tdd-plan.md` (Phase 8 checklist)
