# Feature Spec: Migrate Vapi to LiveKit

> Created: 2026-01-22
> Status: 🟡 Ready for Review
> Previous Vapi repo (for confirmation): `/Users/tom-long/jobs/dev_branch_tmp/Call-agent-squad`

---

## Big picture (what problem are we solving?)
This repo is currently **Vapi-first**: Vapi runs a multi-assistant phone flow and calls our FastAPI backend only for **tool execution** (`POST /vapi/tools`).

We want to migrate the voice runtime from **Vapi → LiveKit**, while keeping the overall architecture “more or less the same”:
- Multi-step call flow stays the same (Customer intake → service collection → booking/confirmation)
- Backend remains a thin, testable tool/DB layer (FastAPI + Postgres)
- Tool contracts stay explicit (tool schemas / “toolspec” as the source of truth)

Clarification: “transfer” in this spec means **migrating the runtime** (Vapi → LiveKit), not implementing a “call transfer” feature.

## Why migrate? (motivations — confirm)
Primary drivers (confirmed): **cost**, **control**, **reliability**.

We should only do this migration if it meaningfully improves at least one of these:
- **Cost / unit economics**: lower or more predictable cost-per-call by owning the realtime pipeline and choosing providers directly (and optionally self-hosting parts).
- **Control / extensibility**: deeper control over turn-taking/endpointing, interruption behavior, retries, and custom behaviors that are hard to express purely in Vapi config.
- **Reliability / vendor risk**: reduce dependence on a single vendor’s uptime and reduce breakage risk from upstream schema/product changes by keeping our backend tool surface stable.
- **Observability / QA**: first-class access to realtime events + metrics (latency, interruption rate, tool-call timing) to debug and improve call quality.
- **Compliance / data handling**: control where audio/transcripts are processed and how long they’re retained.
- **Roadmap**: unlock telephony patterns (inbound + outbound SIP, transfers, etc.) while staying “thin backend + explicit tools”.

Note: we already depend on LiveKit indirectly for Vapi “smart endpointing” (`squad/assistants/customer_intake.json`), so one motivation may be “own the whole pipeline instead of a slice of it.”

Also confirmed: it’s currently **hard to debug calls** and Vapi feels like **black-box magic** (we want more transparent, inspectable runtime behavior).

## Current state (today)
- Vapi Squads orchestrate the conversation + handoffs (CustomerIntake → ServiceCollection → Booking).
- Assistants are configured in `squad/assistants/*.json` (+ `*.prompt.md`) and synced to Vapi via scripts.
- Backend tool adapter: `POST /vapi/tools` → dispatcher → handlers → session store → DB client.
- Key tools: `validate_phone`, `check_customer`, `register_new_customer`, `validate_vin`, `check_vin_database`, `add_service`, `confirm_services`, `get_session_summary`, `store_service_order`, `send_confirmation_sms`, etc.

## Target direction (hypothesis)
Use **LiveKit Agents** for the voice runtime and **LiveKit Telephony (SIP)** to bridge PSTN calls into LiveKit rooms. The LiveKit agent will:
- Join the room when a call arrives
- Run STT/LLM/TTS
- Call our backend tools over HTTP (reusing the existing FastAPI + DB layer)
- Implement the same multi-step flow (either via one agent with a state machine, or multiple agents with handoffs/workflows)

## Constraints / preferences
- Keep the architecture similar to the current “thin backend + tool calls” pattern.
- Keep prompts and tool schemas as versioned files in-repo (like today).

## Decisions (so far)
- **Tool endpoint (Milestone 1)**: keep `POST /vapi/tools` unchanged. The LiveKit runtime will use an **adapter** approach (the LiveKit agent will call the existing endpoint using a Vapi-compatible request/response shape).
- **Vapi runtime**: after cutover, Vapi is **not needed** (keep Vapi configs only as a reference while migrating).
- **Agent structure (Milestone 1)**: use **one LiveKit agent** with internal “phases” (CustomerIntake → ServiceCollection → Booking), instead of multiple agents + handoffs.
- **Call/session id (Milestone 1)**: use the **LiveKit room name** as `message.call.id` when calling `POST /vapi/tools` (easy + stable). Note: some SIP dispatch rules create room names derived from the caller’s phone number; accept this for now, but revisit if we want to avoid PII in IDs/logs.
- **Telephony scope (Milestone 1)**: **inbound only**.

## Migration strategy (phased — draft)
- **Phase 1: LiveKit telephony foundation**: configure LiveKit Telephony (SIP trunk + dispatch rule) so inbound calls create a per-call room and dispatch our agent into it.
- **Phase 2: Agent MVP (thin backend preserved)**: build a LiveKit agent that runs the STT/LLM/TTS loop and calls our existing backend tools via `POST /vapi/tools`.
- **Phase 3: Full call flow parity**: implement the same multi-step flow (intake → service collection → booking/confirmation), reusing the same tool contracts + Postgres-backed session/DB writes.
- **Phase 4: Cutover + cleanup**: route the production phone number to LiveKit and remove Vapi from the runtime path (credentials/configs can remain in-repo for reference until removed).

## Capability mapping (Vapi → LiveKit) (draft)

### Telephony / inbound calls
- **Vapi phone number** → **LiveKit Telephony (SIP trunk + dispatch rule)**.
- In LiveKit, use a dispatch rule that creates a **new room per caller** and dispatches our agent into that room.

### Voice runtime
- **Vapi assistant runtime (STT/LLM/TTS + turn taking)** → **LiveKit Agents runtime**.
- Current Vapi config uses:
  - STT: Deepgram `flux-general-en`
  - LLM: Gemini `gemini-2.5-flash`
  - TTS: ElevenLabs
  - Endpointing: `smartEndpointingPlan.provider = livekit`

### Turn-taking / endpointing (concrete plan)

#### MVP choice: Deepgram Flux endpointing + Silero VAD (closest parity)
Goal: match the current “feels natural + interruptions work” behavior with the fewest moving parts.

- **STT**: Deepgram Flux via LiveKit Deepgram STT plugin (`flux-general-en`).
- **Turn detection**: use STT-based endpointing (`turn_detection="stt"`) so Deepgram’s endpointing determines end-of-turn.
  - Initial tuning knob: `eager_eot_threshold=0.4` (adjust based on real call recordings).
- **Interruptions / barge-in**: enable Silero VAD in the session so we detect user speech quickly and can interrupt agent TTS responsively.

Why this MVP choice:
- It mirrors the current Vapi configuration (Flux STT + endpointing) with minimal new model dependencies.
- It keeps “who decides end-of-turn?” in one place (STT) while still using VAD for fast barge-in.

#### Observability + acceptance criteria (so we can tune)
Add per-call metrics/logs so endpointing changes are data-driven:
- **Barge-in latency**: time from caller starting to speak → agent audio stops.
- **False endpoint rate**: count of times the agent responds while the caller intended to continue (manual QA tag).
- **Dead-air time**: end-of-caller speech → start of agent audio (p50/p95).

Ship criteria for MVP:
- No frequent “talking over the customer” regressions compared to Vapi.
- Calls remain interruptible (caller can cut off TTS and be heard).

#### Follow-up option (if MVP endpointing feels “dumb”): LiveKit turn-detector model
If we see frequent false endpoints (especially around “I need a second…” style pauses), switch to:
- **Turn detection**: LiveKit turn-detector model (context-aware end-of-turn).
- **VAD**: keep Silero VAD.
- **STT**: still required (turn detector needs live STT).

Deployment implication:
- Turn-detector requires downloading model weights and adds CPU/memory cost; consider prewarming to avoid cold-start latency.

### Tools (thin backend preserved)
- **Vapi function tools** → **LiveKit function tools**, but implemented as an HTTP adapter to our backend.
- LiveKit tools should keep the same **tool names** as today so we can reuse prompts/expectations and keep the backend unchanged:
  - `get_case_status`
  - `validate_phone`, `check_customer`, `register_new_customer`, `update_customer`
  - `validate_vin`, `check_vin_database`
  - `add_service`, `confirm_services`, `get_session_summary`
  - `store_service_order`, `update_service_order`, `send_confirmation_sms`
- Implementation note: the LiveKit agent will call `POST /vapi/tools` with a Vapi-compatible payload shape (the backend already supports OpenAI-style `{"function": {"name": "...", "arguments": ...}}` tool calls).

### Multi-step flow / “handoffs”
- **Vapi Squads (handoff between assistants)** → **LiveKit**:
  - Milestone 1: **one agent with an internal “phase” state machine**.
  - Follow-up (optional): multiple agents + LiveKit handoffs/workflows if it improves maintainability.
- The backend currently emits handoff guidance in tool results (example: `next_action: "... Call handoff_to_ServiceCollection."`). For the adapter milestone, the LiveKit runtime should interpret these as **phase transitions** (not Vapi handoffs).

### Session state / IDs
- Current session store is keyed by **Vapi `call.id`** (from the tool request payload).
- LiveKit uses the **room name** as the per-call stable identifier (we pass it as `message.call.id` to reuse the existing session store unchanged).

### Adapter contract: LiveKit Agent → `POST /vapi/tools` (Milestone 1)

#### Why this needs to be explicit
Our existing backend tool logic depends on specific Vapi-shaped fields:
- **Call correlation + session key**: `message.call.id`
- **Caller phone lookup/normalization**: `message.call.customer.number`

If either field is missing or inconsistent, we’ll get regressions (customer lookup fails, phone validation loops, session continuity breaks).

#### Request shape (what the agent sends)
The LiveKit agent must call the existing endpoint with a **Vapi-compatible** JSON payload.

Request payload examples (Milestone 1):

**Always-present fields**
- `message.type = "tool-calls"`
- `message.call.id = "<room_name>"`
- `message.customer.number = <caller ID from SIP when available, else null>`
- `message.toolCallList = [...]`
- `message.assistant.extractedVariables = {}`

**Pre-confirmation example (SIP caller ID available but unconfirmed)**
```json
{
  "message": {
    "type": "tool-calls",
    "call": { "id": "<room_name>" },
    "customer": { "number": "+15551234567" },
    "toolCallList": [
      {
        "id": "tool-call-<uuid>",
        "function": {
          "name": "validate_phone",
          "arguments": "{\"phone_number\":\"+15551234567\"}"
        }
      }
    ],
    "assistant": { "extractedVariables": {} }
  }
}
```

**Post-confirmation example (confirmed callback number)**
```json
{
  "message": {
    "type": "tool-calls",
    "call": { "id": "<room_name>", "customer": { "number": "+15551234567" } },
    "customer": { "number": "+15551234567" },
    "toolCallList": [
      {
        "id": "tool-call-<uuid>",
        "function": {
          "name": "check_customer",
          "arguments": "{\"phone_number\":\"+15551234567\"}"
        }
      }
    ],
    "assistant": { "extractedVariables": {} }
  }
}
```

Implementation rules:
- Populate `message.call.id` **every time** (`room.name`).
- Always confirm/collect a callback number before relying on it for downstream tools.
- Populate `message.customer.number` with the **raw caller number from SIP** when available (unconfirmed).
- Populate `message.call.customer.number` with the **confirmed callback number** only after the user confirms/provides it.
- Prefer `toolCallList` (the backend accepts `toolCalls` too, but `toolCallList` matches Vapi docs + our existing tests).
- Send `function.arguments` as a JSON string for parity with Vapi payloads.

#### LiveKit → Vapi field mapping
**Per-call ID**
- `message.call.id = room.name`

**Caller phone number**
- **Unconfirmed caller number (from SIP)**:
  - `message.customer.number = <caller E.164 phone number from SIP>`
  - Source of truth: the inbound SIP participant’s phone number attribute (example: `sip.phoneNumber`).
  - Fallback: SIP participant identity (if it is E.164).
- **Confirmed callback number (what our backend should rely on)**:
  - `message.call.customer.number = <confirmed callback number>`
  - If SIP number exists: ask the caller to confirm it (“I have you as …, is that the best number?”).
  - If SIP number is missing/withheld: ask the caller for the best callback number.
  - After confirmation, normalize (E.164) and use the confirmed value consistently.

#### Response shape (what the agent expects back)
The backend responds with Vapi tool results format:

```json
{
  "results": [{ "toolCallId": "tool-call-<uuid>", "result": "{\"ok\":true}" }],
  "destination": { "type": "assistant", "assistantId": "<optional>" }
}
```

Agent handling rules:
- Match by `toolCallId`, then JSON-parse `result`.
- Ignore `destination` in Milestone 1 (we’re not doing Vapi handoffs).

## Prompt/workflow migration plan (Milestone 1)

### Goal
Replace Vapi Squads + handoffs with a single LiveKit agent that maintains an explicit **phase**, while preserving:
- the existing tool contract (`POST /vapi/tools`),
- the existing session store keyed by `call.id`,
- and the “get_case_status-driven” behavior already encoded in prompts.

### Pre-flight gate: always confirm/collect callback number
Before running any “business flow” steps, the agent must confirm the callback number:
- If we have a SIP caller number, ask for confirmation first.
- If we don’t have it, collect a callback number first.
- Use `validate_phone` to normalize/validate before proceeding.

Only after the caller confirms/provides a callback number do we proceed to the normal `get_case_status` loop and customer lookup/registration.

### Recommended control loop (keep it deterministic)
Rather than asking the agent LLM to “figure out” when to call which tool, implement a deterministic loop in code:
1. Ensure callback number is confirmed (pre-flight gate above).
2. On each user utterance (after callback confirmation), call `get_case_status(last_user_message=...)` via the adapter.
3. Follow `response_mode`:
   - `speak_first`: speak `immediate_message`, then proceed
   - `tool_first`: run required tool(s) silently, then speak a short outcome
   - `update_first`: apply correction tools, then acknowledge (“Got it”) and continue
4. Use `current_phase` and `ready_for_handoff.*` to move between phases.

This preserves the core architecture you already rely on (backend “case status” as the source of truth) while still using LiveKit for the realtime voice layer.

#### Deterministic vs LLM responsibilities (Milestone 1)
Deterministic in code:
- Enforce the callback-number pre-flight gate.
- Call `get_case_status(last_user_message=...)` once per user turn after the gate.
- Obey `response_mode` ordering (speak-first vs tool-first vs update-first).
- Apply phase transitions when `ready_for_handoff.*` or explicit handoff strings indicate.

LLM-driven (Milestone 1):
- Convert `then_action` / `next_action` text into specific tool calls + arguments (using the tool schemas).

### Phase definitions (single agent)
**Phase 1 — CustomerIntake**
- Objective: confirm callback number (always) + identify/register customer.
- Primary tools: `get_case_status`, `validate_phone`, `check_customer`, `register_new_customer`, `update_customer`.
- Exit: `ready_for_handoff.to_service_collection == true`.

**Phase 2 — ServiceCollection**
- Objective: collect vehicle id + location + complaint; add up to 5 services.
- Primary tools: `get_case_status`, `validate_vin`, `check_vin_database`, `add_service`, `confirm_services`, `update_service_order`.
- Exit: `ready_for_handoff.to_booking == true`.

**Phase 3 — Booking**
- Objective: read back services, confirm, store order, optionally send SMS.
- Primary tools: `get_case_status`, `get_session_summary`, `store_service_order`, `send_confirmation_sms`.
- Exit: order stored (and optional SMS sent) → agent ends call politely.

### How we adapt the existing prompts
Current prompts in `squad/assistants/*.prompt.md` already encode a strong loop:
- Call `get_case_status` every turn with the user’s exact last message.
- Follow `response_mode` + `then_action`.
- Transition phases via handoffs.

In LiveKit Milestone 1, “handoffs” become:
- `handoff_to_ServiceCollection` → `phase = service_collection`
- `handoff_to_Booking` → `phase = booking`
- No separate personas yet; just phase-specific behavior rules.

Optional follow-up (Milestone 2+): if the phase state machine becomes hard to maintain, refactor phases into LiveKit **tasks / task groups** (workflow-style) for better correctness and testability.

## Verification + rollback (draft)

### Verification (what “working” means)
- **Inbound call answers**: dialing the LiveKit-connected phone number results in a LiveKit room being created and the agent joining + speaking.
- **Tools work end-to-end**: the agent can call `POST /vapi/tools` and successfully execute at least:
  - `get_case_status`
  - `validate_phone` (and sees the expected result structure)
  - `add_service` → `get_session_summary` (session continuity)
  - `store_service_order` (writes to Postgres)
- **Debuggability**: we can correlate one call across:
  - agent logs (room name / call id)
  - backend `/vapi/tools` logs (same call id)
  - Postgres rows created for that call

## Automated test plan (Milestone 1)

### 1) Adapter payload unit tests (pure Python)
Goal: lock down Vapi-shaped payload mapping so it can’t regress.

Minimum tests:
- **Expected use**: builds payload with `message.call.id` and (after confirmation) `message.call.customer.number`.
- **Edge case**: SIP phone missing → payload includes `message.customer.number == null` and omits `message.call.customer.number` until user provides one.
- **Failure case**: malformed phone value → adapter refuses/normalizes and forces explicit user collection.

### 2) Agent behavior tests (LiveKit Agents testing framework)
Goal: regression-test conversation logic and tool usage without real audio/telephony.

Approach:
- Use `pytest` + `pytest-asyncio`.
- Use LiveKit’s agent testing helpers in text-mode.
- Mock tools for deterministic behavior (return fixed `get_case_status` outputs, tool results, and failures).

Minimum tests:
- **Expected use (happy path)**: agent confirms callback number first, then proceeds and asks the right next question for the current phase.
- **Edge case**: user provides multiple fields in one utterance → agent advances phase when `ready_for_handoff.*` indicates.
- **Failure case**: tool call fails (HTTP error / non-JSON response) → agent apologizes once and offers retry/fallback (“please call back”).

### 3) Manual smoke test checklist (pre-cutover)
- Inbound call answers within acceptable time (greeting plays).
- Tool calls occur and correlate by `call_id == room.name` across agent logs and backend logs.
- `store_service_order` creates expected Postgres rows in a real environment.

### Rollback (how we undo safely)
- Keep Vapi configs as a reference; for initial cutover, keep a **fast way to reroute** the phone number back to the previous Vapi flow (or to a human fallback) if LiveKit telephony or the agent runtime is unstable.

## Integration (initial)
- Backend tool endpoint (unchanged): `api_server/vapi/router.py` (`POST /vapi/tools`)
- Tool registry / handlers (unchanged): `api_server/vapi/dispatcher.py`, `api_server/vapi/handlers/*`
- Session state (unchanged): `api_server/vapi/session_store.py` (keyed by `call.id`)
- Postgres writes (unchanged): `api_server/server/postgres_client.py`
- New component (to add): a **LiveKit agent service** that:
  - connects to rooms created by LiveKit Telephony, and
  - exposes LiveKit tools that call `POST /vapi/tools` via the adapter payload.

## Deployment / ops (Milestone 1)

### Where the agent runs
The LiveKit agent must run as a **separate long-running service** from the FastAPI backend:
- FastAPI stays a stateless HTTP service for tools + DB.
- The agent service connects to LiveKit, joins rooms on dispatch, runs STT/LLM/TTS, and calls `POST /vapi/tools`.

### LiveKit dispatch (inbound)
Use an inbound SIP setup (SIP provider trunk or LiveKit Phone Numbers) with a dispatch rule that:
- creates one room per inbound call, and
- explicitly dispatches our named agent into that room (recommended for telephony to avoid accidental auto-dispatch).

### Environment variables (agent service)
Minimum:
- `BACKEND_VAPI_TOOLS_URL` (deployed backend `/vapi/tools`)

If using **LiveKit Cloud Agent Deploy**, LiveKit provides these automatically in the agent runtime:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`

If using external providers directly (matching current Vapi setup):
- `DEEPGRAM_API_KEY` (STT)
- `ELEVENLABS_API_KEY` (TTS)
- `GEMINI_API_KEY` (LLM)

### Observability + correlation
Log these for every tool call and phase transition:
- `room_name` (== call_id)
- `sip_phone_number` (if available; consider redaction/hashing)
- tool name + toolCallId

### Runbook essentials
- Deploy to staging first (separate phone number / trunk).
- Keep rollback routing available until stability is proven.
- Document a “kill switch” (stop agent service) and what callers hear when no agent joins (dial tone / silence).

## Requirements

### Must-Have
- [ ] Inbound PSTN calls reach LiveKit rooms via SIP trunk + dispatch rule.
- [ ] A LiveKit agent joins inbound-call rooms and runs STT/LLM/TTS.
- [ ] The agent calls backend tools via `POST /vapi/tools` without changing the backend contract.
- [ ] Tool names and schemas remain explicit and versioned in-repo.
- [ ] Multi-step flow parity (intake → service collection → booking/confirmation) using the existing tools + session store + Postgres writes.
- [ ] Call debugging is improved (clear per-call correlation ID and tool-call logs).
- [ ] Vapi is not required in the runtime path after cutover.

### Nice-to-Have
- [ ] Provider-agnostic tool endpoint (`/tools`) as a follow-up refactor.
- [ ] Multiple LiveKit agents with explicit handoffs (if it improves maintainability).

### Out of Scope (for this spec)
- [ ] Rewriting the FastAPI tool handlers or Postgres layer.
- [ ] Changing tool result semantics / `next_action` strings (unless required for correctness).

## Appendix: Golden path transcript (Milestone 1)

Scenario: inbound call, SIP caller ID present, customer not found, completes booking.

1) Agent joins room → asks to confirm callback number.
   - Tools: none
2) User confirms → agent calls `validate_phone` → `check_customer`.
   - Tools: `validate_phone`, `check_customer`
3) Customer not found → agent collects missing fields → calls `register_new_customer`.
   - Tools: `register_new_customer`
4) Agent proceeds into ServiceCollection and continues via the per-turn `get_case_status` loop.
   - Tools: `get_case_status` (each turn), plus phase-appropriate tools (`validate_vin`, `add_service`, `confirm_services`, etc.)
5) Booking: `store_service_order` → optional `send_confirmation_sms` → end call.

## References (starting points)
- Current architecture docs: `docs/documentations/squad-architecture.md`, `docs/documentations/api-server.md`
- LiveKit docs to consult: Agents (voice), tool calling, telephony/SIP
