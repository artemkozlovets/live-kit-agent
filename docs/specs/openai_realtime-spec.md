# Feature Spec: openai_realtime

> Created: 2026-01-27
> Status: 🟢 Implemented (2026-01-28)

---

## Big picture (what problem are we solving?)
Our current call runtime works, but it can feel **rigid** (turn-taking/barge‑in friction) because we coordinate multiple moving parts:
- **STT** (Deepgram) + **TTS** (Cartesia) + realtime transport (LiveKit)
- backend tool loop + slot-filling guardrails (`get_case_status`, etc.)

This spec moves the *voice/dialogue layer* to **OpenAI Realtime** to improve conversational naturalness, while keeping our **backend-first guardrails** and existing business tooling.

## Goal
Replace the current “STT + (helper LLM) + TTS” stack with **OpenAI Realtime**, while preserving:
- Slot-filling guardrails: **info dump → fill session → ask only missing → confirm at end → book**
- Backend as the source of truth for session state, validation, and booking safety
- Support for **PSTN + web** via LiveKit (rooms + telephony)

## Definitions (to avoid “brain” confusion)
- **Conversation engine**: the realtime model that listens/speaks and produces tool calls (OpenAI Realtime).
- **Policy/state backend**: our FastAPI tool server + session store + DB rules that validate, persist, and enforce “no booking without explicit confirmation”.

## Current state (today)
- Agent voice pipeline:
  - `livekit_agent/agent.py` creates an `AgentSession(...)` using Deepgram STT + Cartesia TTS (`turn_detection="stt"`).
- Tools backend:
  - External endpoint: `POST /vapi/tools` (mounted from `api_server/vapi/router.py`).
  - Slot-filling is opt-in (`AGENT_SLOT_FILLING=1` + backend flags) and works end-to-end.
- Gemini usage:
  - The backend `get_case_status` can make Gemini calls by default (classification/extraction/corrections).
  - The agent can also use Gemini as an optional “tool LLM” to parse `then_action`.

## Pain points (observed)
- Conversation feels “rigid” (turn-taking/barge-in friction; skipped user input; “speech scheduling is paused”).
- “Failed to publish session report” (usually a local env/config issue; not directly solved by Realtime, but we should keep the session report pipeline working).

## Proposed change (target architecture)
**Immediate cutover** to:
- LiveKit remains the transport (PSTN + web).
- OpenAI Realtime becomes the **conversation engine** (audio in/out + tool calling + turn-taking).
- Backend exposes a clean `POST /tools` contract (new simplified payload).
- Backend enforces slot-filling guardrails + explicit booking confirmation.

This spec intentionally **skips** the “Vapi-shaped adapter milestone” from `docs/migrate_vapi_to_livekit-spec.md` and goes straight to a provider-agnostic `/tools` API.

## Key decisions
1. **Architecture**: Option 1 — LiveKit transport + OpenAI Realtime conversation engine + backend tools API.
2. **Control loop (hybrid, explicit)**:
   - The agent **always** calls `get_case_status` each user turn (via `POST /tools`) and supplies the result to the model as context *before* the model responds.
   - The model decides what to say next and which *action tools* to call (validate/register/update/store).
   - The backend remains the final authority (reject unsafe or invalid actions).
3. **Vendor removal (what “remove X from runtime” means)**:
   - **Agent runtime**: remove Deepgram + Cartesia + the optional Gemini “tool LLM” from the default path.
   - **Backend runtime**: disable/remove Gemini-based extraction/classification so calls do not require Google/Gemini to complete.
4. **Cutover strategy**: big-bang **within this repo** (update code/tests/configs together), then delete the legacy `/vapi/*` external surface.

### Rationale
- Fewer realtime components to coordinate in the agent (lower latency + fewer “stuck” states).
- Better turn detection / interruptions by default (Realtime-native).
- Cleaner backend contract (not Vapi-shaped), easier to test and evolve.

## External endpoints
- **Canonical tools endpoint (new):** `POST /tools`
- **Legacy endpoint (deleted after cutover):** `POST /vapi/tools`

Implementation note: we can keep internal module names (`api_server/vapi/...`) temporarily, but the **external** path and docs should become `/tools`.

## Tools API contract (v2, proposed)
Design goals:
- Simple, stable, and **not Vapi-shaped**
- Preserve “pass the whole parent structure” at boundaries (call/customer/assistant context)
- Results match tool call IDs for correlation

### Request
```json
{
  "call": {
    "id": "lk-room-name-or-call-id",
    "customer": { "number": "+15551234567" }
  },
  "customer": { "number": "+15551234567" },
  "assistant": {
    "variable_values": {
      "customerId": "CUST-123",
      "isKnownCustomer": "true"
    }
  },
  "tool_calls": [
    {
      "id": "tool-call-uuid",
      "name": "get_case_status",
      "arguments": {
        "last_user_message": "I'm John Smith and my truck has a flat tire…",
        "expected_field": null
      }
    }
  ]
}
```

Notes:
- `call.id` is the canonical per-call correlation ID (we can keep it == LiveKit room name).
- `customer.number` is the **raw caller ID** when available (unconfirmed).
- `call.customer.number` is the **confirmed callback number** when known (may be omitted until confirmed).
- `assistant.variable_values` is optional but supports “known customer” prefill flows.
- `tool_calls[].arguments` is a JSON object (no JSON-string arguments in v2).
- This **public** v2 contract must remain provider-agnostic. Do not introduce Vapi-specific shapes like `assistantOverrides` (we may map internally for compatibility while reusing existing handlers).

### Response (success)
```json
{
  "results": [
    {
      "tool_call_id": "tool-call-uuid",
      "name": "get_case_status",
      "ok": true,
      "result": { "current_phase": "customer_intake", "missing_fields": ["first_name"] }
    }
  ]
}
```

### Response (per-tool failure)
```json
{
  "results": [
    {
      "tool_call_id": "tool-call-uuid",
      "name": "store_service_order",
      "ok": false,
      "error": {
        "code": "booking_not_confirmed",
        "message": "User has not explicitly confirmed the booking."
      }
    }
  ]
}
```

### HTTP failures
- `400`: invalid request shape (missing `call.id`, invalid `tool_calls`, etc.)
- `401`: missing/invalid auth token
- `500`: unexpected server error (crash w/ stack trace; boundary error handling only)

### Auth (required)
This endpoint must not be publicly callable.
Decision (for this repo):
- Require `X-TOOLS-TOKEN: <shared-secret>` header between agent ↔ backend.
- Backend reads the expected value from env: `TOOLS_TOKEN`.
- Respond with `401` when the header is missing or invalid.

Alternative (nice-to-have later):
- Internal network-only access (private service), plus allowlist by source.

## Guardrails (must keep)
- After initial info dump, populate session state via tools.
- Ask **only** for missing required fields (don’t re-ask known info).
- Before booking, read back a concise summary and request an explicit “yes”.
- Backend enforces: **no booking without explicit confirmation** (the model can’t “self-confirm”).

## Realtime-specific constraints / notes
- Realtime sessions are stateful and time-bounded (confirm exact limits in OpenAI docs).
- Voice selection may be locked after first audio output (choose voice early).
- Known issue: loading large conversation history can cause text outputs even when audio is enabled; if we hit this, use `modalities=["text"]` + a separate TTS plugin as a fallback.
- Realtime models typically do **not** provide interim transcripts. If we later need realtime transcription or the LiveKit “turn detector” model, we must add a separate STT plugin (extra cost). For this cutover, prefer the Realtime model’s built-in VAD.

## Config / dependencies (expected changes)
Agent:
- Add: `OPENAI_API_KEY` (and a model/voice selection env var if we want to make those configurable).
- Remove from the default production path: `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, and the optional `GOOGLE_API_KEY`/`GEMINI_API_KEY` used for “tool LLM” parsing.
- Dependencies: add the LiveKit OpenAI Realtime plugin extra (Python: `livekit-agents[openai]`).
  - Note: `modalities=["text"]` + separate TTS is an optional fallback for history-heavy sessions, but must not be required for MVP or tests.

Backend:
- Add: an auth mechanism for `POST /tools` (for example `X-TOOLS-TOKEN`).
- Default off (or delete): `GET_CASE_STATUS_GEMINI_*` features so calls don’t depend on Gemini.

## Requirements

### Must-have
- [x] OpenAI Realtime is the default conversation engine.
- [x] LiveKit remains the transport for PSTN + web.
- [x] Backend exposes `POST /tools` with the v2 contract above.
- [x] `POST /tools` requires auth (`X-TOOLS-TOKEN` header, validated against `TOOLS_TOKEN`) and returns `401` when missing/invalid.
- [x] Calls complete end-to-end without `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, or `GOOGLE_API_KEY`/`GEMINI_API_KEY` set.
- [x] Preserve slot-filling guardrails: **info dump → fill session → ask only missing → confirm at end → book**.
- [x] Backend enforces “no booking without explicit confirmation”.
- [x] Legacy `POST /vapi/tools` is removed after cutover (404) and `/vapi/*` references are cleaned up.

### Nice-to-have
- [ ] Minimal trace/metrics per call (tool calls, interruptions, latency p50/p95).
- [ ] Avoid PII in `call.id` / room names (do not derive room names from phone numbers).

### Out of scope
- [ ] Backwards compatibility with Vapi payloads or `/vapi/*` paths.
- [ ] Multi-agent handoffs (keep one agent with phases).

## Migration plan (big-bang)
1. Backend: implement `POST /tools` and adapt it to the existing tool registry/handlers.
2. Backend: disable/remove Gemini-based extraction/classification for the Realtime path.
3. Agent: switch `AgentSession` to OpenAI Realtime (remove Deepgram/Cartesia wiring).
4. Agent: update backend URL/config to use `/tools` and remove Vapi-shaped payload generation.
5. Repo-wide: update configs/scripts/docs/tests to point at `/tools`.
6. Cleanup: delete `POST /vapi/tools` and remove `/vapi/*` references from the repo.

## Success criteria
- `POST /tools` accepts the v2 payload and returns the v2 response shape.
- Calls complete end-to-end without Deepgram/Cartesia/Gemini keys present.
- Slot-filling guardrails still hold (ask only missing; explicit confirmation required to book).
- `POST /vapi/tools` no longer exists (404) after cleanup.

## Validation (TDD targets)
- Backend: unit tests for `POST /tools` (happy path, edge case, failure case).
- Agent: slot-filling flow tests updated to hit `/tools` and run in text-mode deterministically.
- Manual smoke: local audio console / web call reaches booking flow and enforces final confirmation.
- Config: agent + backend run without Deepgram/Cartesia/Gemini keys present (only `OPENAI_API_KEY` + `TOOLS_TOKEN`).

## Rollout / rollback (must be explicit)
Rollout:
- Deploy backend `/tools` first (no agent changes yet).
- Deploy agent with `/tools` enabled.
- After stability, remove `/vapi/tools`.

Rollback:
- Keep a single “kill switch” env flag on the agent to fall back to the previous stack (or to stop answering calls) while we investigate.
- Ensure phone routing can be reverted quickly (LiveKit ↔ prior runtime) until stability is proven.

## Integration points (known)
- Agent entry point: `livekit_agent/agent.py`
- Backend tools: new `POST /tools` (FastAPI)
