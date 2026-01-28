# TDD Plan: OpenAI Realtime Cutover (Big-bang)

> Based on: `docs/specs/openai_realtime-spec.md`
> Created: 2026-01-27
> Last Updated: 2026-01-28

---

## Big picture (what problem are we solving?)

Today the call experience can feel rigid because we coordinate multiple realtime parts:
- STT (Deepgram) + TTS (Cartesia) + transport (LiveKit)
- a backend tool loop + slot-filling guardrails (`get_case_status`, etc.)

This plan moves the voice/dialogue layer to **OpenAI Realtime** (better turn-taking + interruptions) while keeping:
- **Backend-first guardrails** and session state
- The existing business tool handlers + DB logic
- LiveKit as the transport for PSTN + web

---

## Success criteria (definition of done)

### Must-have (from the spec)
- [x] **Backend** exposes `POST /tools` that accepts the v2 request and returns the v2 response shape.
- [x] **Auth** required for `POST /tools` (shared secret header `X-TOOLS-TOKEN`).
- [x] **Agent** uses OpenAI Realtime as the default conversation engine.
- [x] Calls complete end-to-end without `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, or `GOOGLE_API_KEY`/`GEMINI_API_KEY` set.
- [x] Slot-filling guardrails still hold: **info dump → fill session → ask only missing → confirm at end → book**.
- [x] Backend enforces **no booking without explicit confirmation**.
- [x] Legacy `POST /vapi/tools` is removed (404) after cutover and `/vapi/*` references are cleaned up.

---

## Traceability matrix (spec → plan validation)

Goal: make it mechanically checkable that this plan covers the spec.

| Spec requirement | Spec ref | Plan validation (test / manual) |
| --- | --- | --- |
| `POST /tools` v2 contract (request + response) | [Tools API contract (v2)](./specs/openai_realtime-spec.md#tools-api-contract-v2-proposed) | Phase 0 + Phase 1 backend tests (`api_server/tests/test_tools_v2_*.py`) |
| `POST /tools` auth required | [Auth (required)](./specs/openai_realtime-spec.md#auth-required) | Phase 0 tests (401 missing/invalid token) |
| Backend remains authority + rejects unsafe actions | [Control loop (hybrid, explicit)](./specs/openai_realtime-spec.md#key-decisions) | Phase 3 booking confirmation tests (backend rejects unconfirmed booking) |
| Disable/remove Gemini for realtime path | [Vendor removal](./specs/openai_realtime-spec.md#key-decisions) | Phase 2 tests (patch Gemini callers to raise; `/tools` still works) |
| OpenAI Realtime is default conversation engine | [Must-have](./specs/openai_realtime-spec.md#must-have) | Phase 5 agent wiring tests + manual smoke (Phase 8) |
| Preserve guardrails (ask only missing; explicit yes to book) | [Guardrails (must keep)](./specs/openai_realtime-spec.md#guardrails-must-keep) | Phase 6 deterministic slot-filling acceptance tests + Phase 8 manual smoke |
| `/vapi/tools` removed after cutover | [External endpoints](./specs/openai_realtime-spec.md#external-endpoints) | Phase 7 tests (404) + repo-wide grep check |

---

## Docs preflight notes (what we’re anchoring on)

### Repo docs (authoritative)
- `docs/specs/openai_realtime-spec.md` (this plan is a direct expansion)
- Existing backend tools router + handlers: `api_server/vapi/*`
- Existing agent slot-filling tests (deterministic): `livekit_agent/tests/test_agent_slot_filling_flow.py`

### External docs (LiveKit Agents)
- OpenAI Realtime plugin usage (Python):
  - `from livekit.plugins import openai`
  - `openai.realtime.RealtimeModel(...)`
  - LiveKit docs: `agents/models/realtime/plugins/openai`
- Testing strategy: text-only tests + tool-call assertions
  - LiveKit docs: `agents/start/testing` (“Testing and evaluation”)

---

## TDD phases overview

We ship in dependency order, while keeping the repo runnable at each step.

```
Phase 0: Backend /tools v2 contract + auth gate
    ↓
Phase 1: Backend v2 tool dispatch adapter (reuse existing handlers)
    ↓
Phase 2: Backend realtime mode (Gemini disabled / fast path)
    ↓
Phase 3: Backend booking confirmation enforcement
    ↓
Phase 4: Agent backend tools client v2 (payload + parsing + auth)
    ↓
Phase 5: Agent OpenAI Realtime session wiring (text-only mode for tests)
    ↓
Phase 6: Deterministic acceptance tests (slot-filling guardrails via /tools)
    ↓
Phase 7: Cleanup (remove /vapi/tools + Vapi payload builder + refs)
    ↓
Phase 8: Manual smoke (console + telephony) + rollback switch
```

---

## Phase 0: Backend `/tools` v2 contract + auth gate

**Goal:** Add `POST /tools` to the FastAPI app with the v2 shape and required auth.

### New modules (proposal)
```
api_server/tools/router.py
api_server/tools/auth.py
api_server/tools/models.py
```

### Auth decision (from spec)
- Require header: `X-TOOLS-TOKEN: <shared-secret>`
- Backend reads expected token from env: `TOOLS_TOKEN`

### Test 0.1 (expected): missing token → 401
**File:** `api_server/tests/test_tools_v2_step_1_auth.py`
- Arrange: `monkeypatch.setenv("TOOLS_TOKEN", "test-secret")`
- Act: `POST /tools` with valid JSON body but no header
- Assert: `401`, and a small JSON error detail

### Test 0.1b (failure): invalid token → 401
**File:** `api_server/tests/test_tools_v2_step_1b_auth_invalid.py`
- Arrange: `monkeypatch.setenv("TOOLS_TOKEN", "test-secret")`
- Act: `POST /tools` with valid JSON body + `X-TOOLS-TOKEN: wrong-secret`
- Assert: `401`

### Test 0.2 (expected): valid token + minimal payload → v2 results shape
**File:** `api_server/tests/test_tools_v2_step_2_endpoint_exists.py`
- Use `validate_phone` (no DB required) as the first tool to dispatch.
- Request:
  - `call.id` present
  - `tool_calls` list length 1 with `id`, `name`, `arguments` (object)
  - `validate_phone` uses `arguments.phone_number` (string)
- Assert response:
  - `200`
  - `results` list length 1
  - result item includes: `tool_call_id`, `name`, `ok` boolean
  - if `ok == true`, `result` is a JSON object (not a JSON string)

### Test 0.3 (failure): invalid request shape → 400
**File:** `api_server/tests/test_tools_v2_step_3_invalid_payload.py`
- Missing `call.id` or `tool_calls` is not a list → `400`

**Implementation notes**
- Keep validation strict in the router: fail fast with `400` on bad shape.
- Do not introduce retries or “best effort” parsing here; this endpoint is agent↔backend only.

---

## Phase 1: Backend v2 tool dispatch adapter (reuse existing handlers)

**Goal:** Route v2 tool calls to the existing tool registry/handlers with minimal churn.

### Adapter strategy (minimal)
- Convert each v2 tool call `{id,name,arguments}` to a Vapi-compatible `tool_call` dict so existing parsing helpers still work.
- Build a `message_payload` that preserves the v2 parent structures:
  - `call` (as-is)
  - `customer` (as-is)
  - Internal compatibility only: map `assistant.variable_values` → `assistantOverrides.variableValues` (so existing `get_case_status` override logic works). Do **not** accept/require `assistantOverrides` in the public v2 request.

### Test 1.1 (expected): multiple tool_calls → multiple correlated results
**File:** `api_server/tests/test_tools_v2_step_4_multi_tool_calls.py`
- Request has 2 tool calls with distinct IDs.
- Assert response has 2 results, each with matching `tool_call_id`.

### Test 1.2 (edge): unknown tool name → per-tool error (ok=false)
**File:** `api_server/tests/test_tools_v2_step_5_unknown_tool.py`
- Tool call name `definitely_not_a_tool`
- Assert:
  - HTTP `200` (request is valid; tool failed)
  - results[0].ok == false
  - results[0].error includes `code` and `message`

### Test 1.3 (edge): variable_values mapping reaches existing override path
**File:** `api_server/tests/test_tools_v2_step_6_variable_values_passthrough.py`
- Send `assistant.variable_values.customerId = "CUST-123"` and `assistant.variable_values.isKnownCustomer = "true"`
- Call `get_case_status`
- Assert response `result.current_phase == "service_collection"` (matches the existing override branch behavior)

**Implementation notes**
- Prefer keeping HTTP `200` for per-tool failures (aligns with v2 examples).
- Reserve HTTP errors for request/auth failures.

---

## Phase 2: Backend realtime mode (Gemini disabled / fast path)

**Goal:** Ensure `/tools` does not incur Gemini latency and does not require any Gemini keys.

### Strategy options (pick one, but keep it explicit)
Option A (recommended): add a “realtime mode” flag in the internal call context and have `get_case_status` default to fast/heuristic behavior when that flag is present.

Option B: create a second handler `handle_get_case_status_realtime` that never calls Gemini code paths.

### Test 2.1 (expected): `/tools` get_case_status does not call Gemini helpers
**File:** `api_server/tests/test_tools_v2_step_7_get_case_status_no_gemini.py`
- Monkeypatch Gemini network helpers to raise if called:
  - `api_server.vapi.message_classifier._generate_gemini_text`
  - `api_server.vapi.message_extractor._generate_gemini_text`
  - (and correction extractor if needed)
- Call `/tools` with `get_case_status`
- Assert: `200`, ok=true, and response contains the expected keys (does not crash).

### Test 2.2 (edge): `/tools` still supports slot-filling extraction via fast path
**File:** `api_server/tests/test_tools_v2_step_8_get_case_status_fast_extracts.py`
- Provide `last_user_message` containing “name/phone/location/vin” info dump
- Assert that at least one extracted field ends up in `result.customer_known_data` or `result.service`

### Test 2.3 (failure): Gemini env flags do not accidentally re-enable network calls
**File:** `api_server/tests/test_tools_v2_step_9_get_case_status_env_flags_ignored.py`
- Set `GET_CASE_STATUS_GEMINI_EXTRACTION=1` in env
- Still assert Gemini helpers were not called for `/tools`

---

## Phase 3: Backend booking confirmation enforcement

**Goal:** Backend enforces “no booking without explicit confirmation” regardless of what the model says.

### Decision (minimal + explicit)
- Reuse existing `confirm_services` tool as the explicit confirmation latch.
- Update `store_service_order` to fail fast unless `session["services_confirmed"] == True`.
- Error contract in v2:
  - `ok: false`
  - `error.code: "booking_not_confirmed"`
  - `error.message`: short, caller-safe message

### Test 3.1 (failure): store_service_order without confirmation → booking_not_confirmed
**File:** `api_server/tests/test_tools_v2_step_10_booking_requires_confirmation.py`
- Arrange session with:
  - `customer_id` present
  - `services` present
  - `services_confirmed` missing/false
- Call `/tools` with `store_service_order`
- Assert ok=false and error.code == `booking_not_confirmed`
- Assert DB client is not called (fail fast before writes)

### Test 3.2 (expected): confirm_services then store_service_order → success
**File:** `api_server/tests/test_tools_v2_step_11_booking_happy_path_confirm_then_store.py`
- Use dependency override for `get_database_client` with an in-test fake (pattern from existing Step 7 tests).
- Arrange session with customer + services
- Call `/tools`:
  1) `confirm_services`
  2) `store_service_order`
- Assert both ok=true and the second result contains order IDs

### Test 3.3 (edge): confirm_services without customer_id → ok=false (guardrail)
**File:** `api_server/tests/test_tools_v2_step_12_confirm_requires_customer.py`
- Arrange session missing `customer_id`
- Call `/tools` with `confirm_services`
- Assert ok=false and error contains a useful `message`

---

## Phase 4: Agent backend tools client v2 (payload + parsing + auth)

**Goal:** Replace Vapi-shaped payload generation with the v2 `/tools` contract and parse v2 results.

### New module (proposal)
```
livekit_agent/tools_v2_payload.py
```

### Payload builder API (proposal)
```python
def build_tools_v2_request(
    *,
    call_id: str,
    customer_number_raw: str | None,
    call_customer_number_confirmed: str | None,
    assistant_variable_values: dict[str, str] | None,
    tool_calls: list[dict[str, object]],
) -> dict[str, object]:
    ...
```

### Test 4.1 (expected): client sends v2 payload + auth header
**File:** `livekit_agent/tests/test_backend_tools_client_v2_step_1_payload.py`
- Inject `post_json(url, payload, headers=...)` (update DI shape as needed)
- Assert:
  - URL ends with `/tools`
  - Payload includes `call.id`
  - Tool call arguments are a dict (not JSON string)
  - Header includes `X-TOOLS-TOKEN`

### Test 4.2 (edge): client matches results by tool_call_id
**File:** `livekit_agent/tests/test_backend_tools_client_v2_step_2_matching.py`
- Response contains two results; client returns the matching one.

### Test 4.3 (failure): ok=false maps to a typed exception
**File:** `livekit_agent/tests/test_backend_tools_client_v2_step_3_error_mapping.py`
- Backend returns `ok:false` and `error.code == "booking_not_confirmed"`
- Client raises a dedicated exception type (or a structured error object) so agent can branch cleanly.

---

## Phase 5: Agent OpenAI Realtime session wiring (text-only for tests)

**Goal:** Make OpenAI Realtime the default conversation engine while keeping tests deterministic.

### Implementation strategy (hybrid, explicit)
- Use OpenAI Realtime plugin for the session LLM:
  - `from livekit.plugins import openai`
  - `openai.realtime.RealtimeModel(...)`
- Configure text-only mode for tests and (optionally) for deterministic local runs:
  - `modalities=["text"]`
- Turn detection:
  - Prefer the Realtime model’s built-in VAD (do not add a separate STT plugin for MVP/tests).
- Remove the agent-side “tool LLM” parsing path (Gemini): rely on Realtime tool/function calling + backend validation.
- Register tool schemas from `squad/assistants/*.json` as function tools, implemented as “forward to backend `/tools`”.
- Explicitly call `get_case_status` on every user turn **before** generating a reply, and inject the result as context.

### Test 5.1 (expected): agent calls get_case_status before generating reply
**File:** `livekit_agent/tests/test_openai_realtime_agent_step_1_turn_hook.py`
- Use a fake session object (or monkeypatch `AgentSession.generate_reply`) to observe call order:
  - `backend.call_tool("get_case_status", ...)` happens first
  - then `session.generate_reply(...)`
- Assert the case_status JSON is present in the turn’s context (system message or metadata)

### Test 5.2 (edge): tool forwarding uses v2 endpoint and passes whole parent structure
**File:** `livekit_agent/tests/test_openai_realtime_agent_step_2_tool_forwarding.py`
- Simulate the model calling `validate_phone` with malformed args.
- Assert the agent forwards:
  - raw caller number in `customer.number`
  - confirmed callback number in `call.customer.number` (if known)
  - preserves `assistant.variable_values`

### Test 5.3 (failure): backend unreachable → fail fast + user-safe fallback
**File:** `livekit_agent/tests/test_openai_realtime_agent_step_3_backend_down.py`
- BackendToolsClient raises `BackendToolsTransportError`
- Assert agent speaks a single short fallback and does not loop/tool-spam

### Test 5.4 (expected): agent does not require Deepgram/Cartesia/Gemini env
**File:** `livekit_agent/tests/test_openai_realtime_agent_step_4_no_legacy_keys.py`
- Clear `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `GOOGLE_API_KEY`/`GEMINI_API_KEY` from env (monkeypatch).
- Assert agent session initialization succeeds with only `OPENAI_API_KEY` present.
- (Optional) Monkeypatch Deepgram/Cartesia/Gemini constructors to raise if called and assert they are not invoked on the Realtime default path.

---

## Phase 6: Deterministic acceptance tests (slot-filling guardrails via `/tools`)

**Goal:** Prove the full “info dump → fill session → ask only missing → confirm → book” loop still works with the new `/tools` contract.

### Approach (keep tests deterministic)
- Continue to run agent tests in text mode with a stubbed backend (`post_json` injection) like existing tests.
- Update the stubbed backend to accept v2 payloads and return v2 responses.

### Test 6.1 (expected): info dump to booking (requires explicit confirm)
**File:** `livekit_agent/tests/test_agent_slot_filling_flow_v2_step_1.py`
- Turn 1: info dump populates session via `get_case_status`, then agent/model asks final confirmation.
- Turn 2: user says “yes” → agent/model calls `confirm_services` then `store_service_order`.
- Assert tool call order includes both confirm + store.

### Test 6.2 (edge): caller says “no” at confirmation → does not book
**File:** `livekit_agent/tests/test_agent_slot_filling_flow_v2_step_2_decline_confirmation.py`
- After the summary prompt, user says “no”
- Assert no `store_service_order` call occurs

### Test 6.3 (failure): backend returns booking_not_confirmed → agent recovers by re-confirming
**File:** `livekit_agent/tests/test_agent_slot_filling_flow_v2_step_3_booking_guardrail.py`
- Simulate backend rejecting booking
- Assert agent asks for explicit confirmation again (or calls `confirm_services` first)

---

## Phase 7: Cleanup (remove `/vapi/tools` + Vapi adapter artifacts)

**Goal:** Remove legacy external surface and delete Vapi-shaped adapter code after `/tools` is stable.

### Test 7.1 (expected): `/vapi/tools` returns 404
**File:** `api_server/tests/test_tools_v2_step_13_vapi_removed.py`
- `POST /vapi/tools` should be `404` after cleanup.

### Test 7.2 (repo-wide): no `/vapi/` references remain (except docs/history)
- Add a small script or a test that `rg "/vapi/"` returns empty for runtime code paths.

### Deletions / migrations (plan-only; do when all tests pass)
- Remove `api_server.vapi.router` inclusion from `api_server/server/fastapi_app.py`
- Remove `livekit_agent/vapi_payload.py` and any usage
- Update defaults in `README.md`, `squad/assistants/*.json`, and env var names:
  - `BACKEND_TOOLS_URL` should point to `/tools`

---

## Phase 8: Manual smoke + rollout/rollback

**Goal:** Validate the real audio path (console + telephony) and keep rollback explicit.

### Manual smoke checklist (local)
- Start backend locally and verify:
  - `POST /tools` works with auth and tool dispatch
- Start agent in console mode:
  - `python -m livekit_agent.agent console`
- Talk through:
  1) Info dump
  2) Missing-field questioning (only missing fields)
  3) Summary + explicit “yes”
  4) Booking succeeds
- Try “no” at confirmation → booking blocked
- Verify the session report pipeline still succeeds (no “Failed to publish session report” regressions)

### Telephony smoke checklist (staging)
- Inbound PSTN call reaches LiveKit room
- Agent joins room and can be interrupted (barge-in)
- Booking requires explicit confirmation (backend enforcement)

### Rollout/rollback lever (required)
- Add a single agent env flag (kill switch) to:
  - disable answering calls, or
  - fall back to the previous stack while investigating
  - Implemented: `AGENT_ENGINE=legacy` uses the previous Deepgram+Cartesia pipeline (default is `openai_realtime`).

---

## TDD Execution Log

- ✅ 0.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_missing_token_returns_401`
  - Decision: Added a new `POST /tools` surface with a strict `X-TOOLS-TOKEN` auth gate (env `TOOLS_TOKEN`) before implementing any dispatch logic.
- ✅ 0.1b (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_invalid_token_returns_401`
  - Decision: Treat missing/invalid tokens identically (`401 Unauthorized`) to avoid leaking auth details.
- ✅ 0.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_valid_token_dispatches_validate_phone`
  - Decision: Reused existing `api_server.vapi.dispatcher.dispatch_tool_call` with a v1-compatible `message_payload` shim so we can cut over without rewriting all handlers.
- ✅ 0.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_invalid_payload_returns_400`
  - Decision: Implemented explicit request-shape validation in the router to return `400` (not FastAPI’s default `422`) for bad agent↔backend payloads.
- ✅ 1.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_multiple_tool_calls_return_multiple_correlated_results`
  - Decision: Kept v2 result correlation purely by `tool_call_id` to make tool batching deterministic.
- ✅ 1.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_unknown_tool_returns_ok_false_with_error`
  - Decision: Unknown tool names are treated as per-tool failures (`HTTP 200`, `ok=false`) to match the v2 contract.
- ✅ 1.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_variable_values_map_into_existing_override_path`
  - Decision: Mapped v2 `assistant.variable_values` into internal `assistantOverrides.variableValues` so existing known-customer overrides remain unchanged.
- ✅ 2.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_get_case_status_does_not_call_gemini`
  - Decision: Added an explicit `/tools` “realtime mode” in `get_case_status` that forces non-network (heuristic + fast extractor) behavior.
- ✅ 2.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_get_case_status_fast_path_extracts_fields`
  - Decision: Enabled slot-filling + fast extraction by default for `/tools` so “info dump” turns actually populate session state without Gemini.
- ✅ 2.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_gemini_env_flags_do_not_reenable_network_calls`
  - Decision: `/tools` ignores all `GET_CASE_STATUS_GEMINI_*` env flags to prevent accidental network reintroduction.
- ✅ 3.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_store_service_order_requires_explicit_confirmation`
  - Decision: Enforced booking confirmation at the `/tools` boundary to guarantee “fail fast before DB writes” without impacting the legacy `/vapi/tools` path during the transition.
- ✅ 3.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_confirm_services_then_store_service_order_succeeds`
  - Decision: Allowed multi-tool batching in a single `/tools` request; sequential dispatch means `confirm_services` can unlock `store_service_order` in the same call.
- ✅ 3.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_confirm_services_requires_customer_id`
  - Decision: Kept guardrails in the tool layer (confirm requires customer_id) and surfaced them as v2 `ok=false` errors.
- ✅ 4.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_backend_tools_client_v2_sends_v2_payload_and_auth_header`
  - Decision: Added a v2 mode to `BackendToolsClient` that builds provider-agnostic `/tools` payloads and sends `X-TOOLS-TOKEN` (read from `TOOLS_TOKEN` by default).
- ✅ 4.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_backend_tools_client_v2_matches_results_by_tool_call_id`
  - Decision: Matched tool results strictly by `tool_call_id` so batching is safe even when tools return out of order.
- ✅ 4.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_backend_tools_client_v2_maps_booking_not_confirmed`
  - Decision: Mapped `booking_not_confirmed` into a dedicated exception (`BookingNotConfirmedError`) so the agent can branch without string parsing.
- ✅ 5.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_openai_realtime_agent_calls_get_case_status_before_generate_reply`
  - Decision: Implemented an explicit “pre-turn hook” that injects backend `case_status` into `ChatContext` before calling `session.generate_reply`.
- ✅ 5.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_openai_realtime_agent_tool_forwarding_preserves_parent_structure`
  - Decision: Tool forwarding uses `BackendToolsClient(use_tools_v2=True)` so raw/confirmed phone numbers and `assistant.variable_values` flow into the v2 payload unchanged.
- ✅ 5.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_openai_realtime_agent_backend_down_speaks_one_fallback`
  - Decision: Backend transport failures trigger a single short fallback and then hard-stop the agent to prevent repeated tool spam.
- ✅ 5.4 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_openai_realtime_session_does_not_require_legacy_vendor_keys`
  - Decision: Added a small OpenAI Realtime session factory that does not reference Deepgram/Cartesia/Gemini env vars (plugin import is lazy).
- ✅ 6.1 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_agent_slot_filling_v2_info_dump_to_booking_requires_confirm_then_store`
  - Decision: When using `/tools` (v2), the slot-filling flow explicitly calls `confirm_services` before `store_service_order` to satisfy backend booking enforcement.
- ✅ 6.2 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_agent_slot_filling_v2_decline_confirmation_does_not_book`
  - Decision: A “no” at the final confirmation prompt blocks booking and shifts the agent into correction mode (no store attempt).
- ✅ 6.3 (2026-01-27T23:34:06Z) `.venv/bin/python -m pytest -q livekit_agent/tests -k test_agent_slot_filling_v2_booking_not_confirmed_prompts_again`
  - Decision: If the backend returns `booking_not_confirmed`, the agent safely re-prompts for explicit confirmation instead of retrying bookings automatically.
- ✅ 7.1 (2026-01-28T00:17:13Z) `.venv/bin/python -m pytest -q api_server/tests -k test_vapi_tools_removed_returns_404`
  - Decision: Removed the legacy external surface (`POST /vapi/tools`) so only the provider-agnostic `/tools` endpoint remains.
- ✅ 7.2 (2026-01-28T00:21:46Z) `.venv/bin/python -m pytest -q api_server/tests -k test_repo_contains_no_vapi_path_references`
  - Decision: Added a repo-wide guard test to prevent reintroducing hardcoded `/vapi/` URL paths after the cutover to `/tools`.
- ✅ 7.3 (2026-01-28T00:57:42Z) `./scripts/test_all.sh`
  - Decision: Removed the legacy agent-side Vapi payload builder and made `BackendToolsClient` v2-only; `AGENT_ENGINE` is the explicit rollback lever.
- ✅ Docs (2026-01-28T01:14:43Z) `./scripts/test_all.sh`
  - Decision: Updated repo docs to reflect `/tools` v2 + `X-TOOLS-TOKEN` auth, OpenAI Realtime default (`AGENT_ENGINE=openai_realtime`), and marked legacy Vapi migration docs as deprecated; also updated log filtering guidance to use `/tools`.
