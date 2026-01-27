# TDD Plan: Migrate Vapi → LiveKit (Milestone 1)

> Based on: `docs/specs/migrate_vapi_to_livekit-spec.md`
> Previous Vapi repo (for confirmation): `/Users/tom-long/jobs/dev_branch_tmp/Call-agent-squad`
> Created: 2026-01-22
> Last Updated: 2026-01-22

---

## Big picture (what problem are we solving?)

Today, Vapi runs our phone call runtime and calls our backend only for tool execution (`POST /vapi/tools`).

This plan migrates the **voice runtime** from **Vapi → LiveKit**, while keeping the backend “thin” and stable:
- Keep `POST /vapi/tools` unchanged (LiveKit agent uses a Vapi-shaped adapter payload)
- Preserve tool contracts as explicit, versioned files in-repo (`squad/assistants/*.json`)
- Preserve the multi-step call flow (CustomerIntake → ServiceCollection → Booking), but run it in **one LiveKit agent** with an explicit phase/state machine

---

## Milestone 1 success criteria (definition of done)

### Must-have (from the spec)
- [ ] Inbound PSTN calls reach LiveKit rooms via SIP trunk + dispatch rule.
- [ ] A LiveKit agent joins inbound-call rooms and runs STT/LLM/TTS.
- [ ] The agent calls backend tools via `POST /vapi/tools` **without changing the backend contract**.
- [ ] Multi-step flow parity (intake → service collection → booking/confirmation) using the existing tools + session store + Postgres writes.
- [ ] Improved debugging: per-call correlation (room name == call_id) visible in agent logs + backend logs + Postgres rows.
- [ ] Vapi is not required in the runtime path after cutover.

---

## Traceability matrix (spec → plan validation)

Goal: make it mechanically checkable that this plan covers the spec.

| Spec requirement | Spec ref | Plan validation (test / manual) |
| --- | --- | --- |
| Inbound PSTN calls reach LiveKit rooms via SIP trunk + dispatch rule | [Spec: Telephony / inbound calls](../specs/migrate_vapi_to_livekit-spec.md#telephony--inbound-calls) | Manual smoke checklist (Phase 4) + staging call-through |
| Agent joins inbound rooms and runs STT/LLM/TTS | [Spec: Target direction](../specs/migrate_vapi_to_livekit-spec.md#target-direction-hypothesis) | Manual smoke checklist (Phase 4) + agent startup/runbook |
| Agent calls backend tools via `POST /vapi/tools` without changing backend contract | [Spec: Adapter contract](../specs/migrate_vapi_to_livekit-spec.md#adapter-contract-livekit-agent--post-vapitools-milestone-1) | Phase 1 payload builder unit tests + Phase 2 backend tools client unit tests |
| Always confirm/collect callback number before “business flow” tools (Option A) | [Spec: Pre-flight gate](../specs/migrate_vapi_to_livekit-spec.md#pre-flight-gate-always-confirmcollect-callback-number) | Phase 0 agent gate unit test (no `get_case_status` until confirmed) |
| Multi-step flow parity (intake → service collection → booking/confirmation) | [Spec: Deterministic loop](../specs/migrate_vapi_to_livekit-spec.md#recommended-control-loop-keep-it-deterministic) | Phase 4 deterministic text-mode acceptance test (stub `get_case_status` outputs → assert phase transitions) |
| Postgres writes via `store_service_order` (service orders persist + session completes) | [Spec: Verification](../specs/migrate_vapi_to_livekit-spec.md#verification-what-working-means) | Existing backend tests (ex: `api_server/tests/test_vapi_adapter_step_7_store_service_order.py`) + manual smoke checklist (Phase 4) |
| Tool names/schemas remain explicit and versioned in-repo | [Spec: Constraints / tools](../specs/migrate_vapi_to_livekit-spec.md#constraints--preferences) | Phase 3 schema loading test from `squad/assistants/*.json` |
| Per-call correlation: `room.name == call_id` visible across logs + Postgres rows | [Spec: Call/session id](../specs/migrate_vapi_to_livekit-spec.md#decisions-so-far) | Phase 1 payload builder asserts `message.call.id`; manual smoke checklist confirms correlation across systems |
| Vapi not required in runtime after cutover | [Spec: Migration strategy](../specs/migrate_vapi_to_livekit-spec.md#migration-strategy-phased--draft) | Manual cutover checklist + remove Vapi from call path |

---

## Docs preflight notes (what we’re anchoring on)

### Backend contract we must satisfy
The backend expects a Vapi-shaped webhook payload at `POST /vapi/tools` and returns a Vapi-style `{ "results": [...] }` response. See:
- Existing backend behavior: `api_server/vapi/router.py`
- Existing Vapi docs examples for `toolCallList` + response format: `docs.vapi.ai/tools/custom-tools`

### LiveKit telephony key facts (for payload mapping)
- SIP inbound calls create a SIP participant and put them into a room per dispatch rule.
- SIP participants expose caller info as `sip.phoneNumber` (may be hidden if `hidePhoneNumber` is set on the dispatch rule).

---

## TDD phases overview

We’ll ship Milestone 1 in **5 phases**, ordered by dependency:

```
Phase 0: Contract gates (backend + payload shape)
    ↓
Phase 1: Vapi payload builder (pure Python)
    ↓
Phase 2: Backend tools client (HTTP + parsing + failures)
    ↓
Phase 3: LiveKit tool registry (schemas from squad JSON)
    ↓
Phase 4: Agent behavior tests (text-only + telephony smoke checklist)
```

---

## Phase 0: Contract gates (backend + payload shape)

**Goal:** Lock down the payload fields the agent must send, without changing the backend contract, and make the phone-number trust model explicit (Option A).

### Decision (Option A): do not use unconfirmed caller ID for customer lookup
We will **not** change the backend to treat `message.customer.number` as a fallback for `get_case_status`.

Reason: `message.customer.number` will be populated from the raw SIP caller ID when available, and it is **not confirmed**. Using it for customer lookup can:
- leak PII (“Hey John…”) before the caller confirms this is their best callback number
- couple the backend’s logic to telephony provider quirks (withheld/spoofed/forwarded numbers)

Instead, we enforce a strict gate in the agent:
1) Collect/confirm a callback number (if SIP has a number, ask “Is +1… the best number?”).
2) Call `validate_phone` to normalize it.
3) Call `check_customer(phone_number=...)` (and `register_new_customer` if needed) **using the confirmed callback number**.
4) Only then enter the deterministic `get_case_status(last_user_message=...)` loop.

This keeps the backend unchanged while preventing “unconfirmed phone → lookup → personalization” behavior.

### Test 0.1 (expected): no `get_case_status` call before callback number is confirmed
Write a pure unit test around our flow controller that asserts:
- with `sip_phone_number` present but not confirmed, the next action is a *prompt to confirm* (and no backend tool call)
- after confirmation + `validate_phone`, we call `check_customer` before `get_case_status`

### Test 0.2 (edge): caller rejects SIP number → we collect a new callback number
Assert the controller:
- never calls `check_customer`/`get_case_status` with the SIP number if the caller rejects it
- uses the caller-provided callback number after `validate_phone`

### Test 0.3 (failure): invalid phone number path is bounded
Assert the controller:
- retries `validate_phone` up to a small max
- then falls back to “proceed unvalidated” behavior that mirrors the backend’s `validate_phone` semantics (no infinite loops)

---

## Phase 1: Vapi payload builder (pure Python)

**Goal:** A single, testable function that builds the exact payload shape we will send from LiveKit → backend.

### New module
```
livekit_agent/vapi_payload.py
```

### API (proposal)
```python
def build_vapi_tool_call_request(
    *,
    call_id: str,
    sip_phone_number: str | None,
    confirmed_callback_number: str | None,
    tool_call_id: str,
    tool_name: str,
    tool_arguments: dict,
) -> dict:
    ...
```

### Test 1.1 (expected): includes `message.call.id`, `message.customer.number`, and `message.call.customer.number` (when confirmed)
```python
# File: livekit_agent/tests/test_vapi_payload.py

import json

from livekit_agent.vapi_payload import build_vapi_tool_call_request


def test_build_vapi_tool_call_request_happy_path() -> None:
    payload = build_vapi_tool_call_request(
        call_id="room-123",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_call_id="tool-call-abc",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+15551230000"},
    )

    message = payload["message"]
    assert message["type"] == "tool-calls"
    assert message["call"]["id"] == "room-123"
    assert message["customer"]["number"] == "+15551230000"
    assert message["call"]["customer"]["number"] == "+15551230000"

    tool_call = message["toolCallList"][0]
    assert tool_call["id"] == "tool-call-abc"
    assert tool_call["function"]["name"] == "validate_phone"
    assert isinstance(tool_call["function"]["arguments"], str)

    # Reason: backend supports dict too, but we prefer JSON-string parity with Vapi.
    parsed = json.loads(tool_call["function"]["arguments"])
    assert parsed == {"phone_number": "+15551230000"}
```

### Test 1.2 (edge): SIP number missing → include `message.customer.number == None` and omit `call.customer.number`
```python
def test_build_vapi_tool_call_request_no_sip_phone_number() -> None:
    payload = build_vapi_tool_call_request(
        call_id="room-456",
        sip_phone_number=None,
        confirmed_callback_number=None,
        tool_call_id="tool-call-1",
        tool_name="get_case_status",
        tool_arguments={"last_user_message": "Hello"},
    )

    message = payload["message"]
    assert message["customer"]["number"] is None
    assert "customer" not in message["call"]  # omit until confirmed
```

### Test 1.3 (failure): missing required identifiers raises
```python
import pytest


def test_build_vapi_tool_call_request_requires_call_id() -> None:
    with pytest.raises(ValueError):
        build_vapi_tool_call_request(
            call_id="",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )
```

### Test 1.4 (edge): multiple tool calls can be sent in one `toolCallList`
**Why:** Vapi can send multiple tool calls at once, and the backend returns multiple results. Even if we mostly call one tool at a time in Milestone 1, this keeps the adapter contract robust.

Implementation approach:
- Add `build_vapi_tool_calls_request(..., tool_calls=[...])`
- Keep `build_vapi_tool_call_request(...)` as a thin wrapper around the multi-call builder.

```python
import json

from livekit_agent.vapi_payload import build_vapi_tool_calls_request


def test_build_vapi_tool_calls_request_multiple_tool_calls() -> None:
    payload = build_vapi_tool_calls_request(
        call_id="room-123",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_calls=[
            {
                "id": "tool-call-1",
                "name": "check_customer",
                "arguments": {"phone_number": "+15551230000"},
            },
            {
                "id": "tool-call-2",
                "name": "get_case_status",
                "arguments": {"last_user_message": "Hi"},
            },
        ],
    )

    tool_calls = payload["message"]["toolCallList"]
    assert [tc["id"] for tc in tool_calls] == ["tool-call-1", "tool-call-2"]
    assert [tc["function"]["name"] for tc in tool_calls] == ["check_customer", "get_case_status"]
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"phone_number": "+15551230000"}
    assert json.loads(tool_calls[1]["function"]["arguments"]) == {"last_user_message": "Hi"}
```

---

## Phase 2: Backend tools client (HTTP + parsing + failures)

**Goal:** A small client used by our LiveKit tools that:
- sends the payload from Phase 1
- parses `{ "results": [...] }` correctly
- fails fast and predictably on errors (timeouts, non-200, invalid JSON)

### New module
```
livekit_agent/backend_tools_client.py
```

### Test 2.1 (expected): parses Vapi `{results:[{toolCallId,result}]}` into a dict
```python
# File: livekit_agent/tests/test_backend_tools_client.py

import json
import pytest

from livekit_agent.backend_tools_client import BackendToolsClient


@pytest.mark.asyncio
async def test_backend_tools_client_parses_tool_result() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        assert url == "https://backend.test/vapi/tools"
        assert payload["message"]["call"]["id"] == "room-1"
        return {
            "results": [
                {"toolCallId": "tool-call-1", "result": json.dumps({"ok": True})},
            ],
            "destination": {"type": "assistant", "assistantId": "ignored"},
        }

    client = BackendToolsClient(
        tools_url="https://backend.test/vapi/tools",
        post_json=fake_post_json,
    )

    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number="+15551230000",
        confirmed_callback_number="+15551230000",
        tool_call_id="tool-call-1",
        tool_name="validate_phone",
        tool_arguments={"phone_number": "+15551230000"},
    )

    assert result == {"ok": True}
```

### Test 2.2 (edge): multiple results returned → select by `toolCallId` (not by list order)
```python
@pytest.mark.asyncio
async def test_backend_tools_client_selects_matching_tool_call_id() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        return {
            "results": [
                {"toolCallId": "tool-call-other", "result": json.dumps({"ok": False})},
                {"toolCallId": "tool-call-1", "result": json.dumps({"ok": True})},
            ],
            "destination": {"type": "assistant", "assistantId": "ignored"},
        }

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    result = await client.call_tool(
        call_id="room-1",
        sip_phone_number=None,
        confirmed_callback_number=None,
        tool_call_id="tool-call-1",
        tool_name="get_case_status",
        tool_arguments={"last_user_message": "Hi"},
    )

    assert result == {"ok": True}
```

### Test 2.3 (failure): missing/mismatched `toolCallId` in results → raise a typed error
```python
@pytest.mark.asyncio
async def test_backend_tools_client_missing_tool_call_id_raises() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        return {"results": [{"toolCallId": "tool-call-other", "result": json.dumps({"ok": True})}]}

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    with pytest.raises(Exception):  # replace with ToolResultMissingError
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )
```

### Test 2.4 (edge): backend returns non-JSON `result` → raise a typed error
```python
@pytest.mark.asyncio
async def test_backend_tools_client_invalid_result_raises() -> None:
    async def fake_post_json(url: str, payload: dict) -> dict:
        return {"results": [{"toolCallId": "tool-call-1", "result": "not-json"}]}

    client = BackendToolsClient(tools_url="https://backend.test/vapi/tools", post_json=fake_post_json)

    with pytest.raises(Exception):  # replace with ToolResultParseError
        await client.call_tool(
            call_id="room-1",
            sip_phone_number=None,
            confirmed_callback_number=None,
            tool_call_id="tool-call-1",
            tool_name="get_case_status",
            tool_arguments={"last_user_message": "Hi"},
        )
```

### Test 2.5 (failure): non-200/timeout → raise and let the agent boundary handle it
Simulate `post_json` raising `TimeoutError` and assert we bubble a single, explicit exception type.

---

## Phase 3: LiveKit tool registry (schemas from squad JSON)

**Goal:** In LiveKit, expose the same tool “surface” as Vapi, without duplicating schemas in two places.

### Design rule
Load tool schemas from:
- `squad/assistants/customer_intake.json`
- `squad/assistants/service_collection.json`
- `squad/assistants/booking.json`

and build LiveKit function tools from those schemas (plus our local “handoff” phase tools).

### New module
```
livekit_agent/tools.py
```

### Test 3.1 (expected): we can load and de-duplicate all tool schemas
```python
# File: livekit_agent/tests/test_tool_schema_loading.py

from livekit_agent.tools import load_tool_schemas


def test_load_tool_schemas_includes_expected_backend_tools() -> None:
    schemas = load_tool_schemas()
    names = {schema["name"] for schema in schemas}

    assert "get_case_status" in names
    assert "validate_phone" in names
    assert "check_customer" in names
    assert "register_new_customer" in names
    assert "add_service" in names
    assert "store_service_order" in names
```

### Test 3.2 (edge): include local “handoff tools” even though they aren’t `type:function` in Vapi JSON
We’ll define local LiveKit tools:
- `handoff_to_ServiceCollection`
- `handoff_to_Booking`
- `handoff_to_CustomerIntake` (optional)

### Test 3.3 (failure): missing/invalid assistant JSON fails fast
If any `squad/assistants/*.json` is invalid JSON, `load_tool_schemas()` should raise with a clear message.

---

## Phase 4: Agent behavior tests (text-only + telephony smoke checklist)

**Goal:** Validate the LiveKit agent’s behavior and tool usage without real audio/telephony first, then do a staged telephony smoke test.

### New module (agent entrypoint)
```
livekit_agent/agent.py
```

### Dependency note (requires approval when implementing)
This phase will add new dependencies (e.g. `livekit-agents[...]`) and will require updating `requirements.txt` (config change) — **ask before editing**.

### Test strategy
1) **Unit tests** for our adapter + backend client (Phases 1–2) run with no external keys.
2) **Behavioral tests** for the agent can be *integration-style* and skip unless keys are present (same pattern as `api_server/tests/integration/*`).

### Test 4.0 (expected): deterministic phase transitions from tool outputs (text-only)
Goal: prove “flow parity” at the control-logic layer *without* LiveKit, audio, or provider keys.

Write a pure Python test for a small `FlowController`/state-machine that:
- starts in `customer_intake`
- refuses to call `get_case_status` until a callback number is confirmed (Option A gate)
- updates `phase` when backend tool results contain handoff strings in `next_action`
- updates `phase` when `get_case_status.ready_for_handoff.*` indicates a transition

Acceptance assertions (single test case is fine):
1) Before confirmation: `can_call_get_case_status == false`
2) After confirmation: `can_call_get_case_status == true`
3) Given a tool result with `next_action` containing `handoff_to_ServiceCollection` → phase becomes `service_collection`
4) Given `get_case_status` result with `ready_for_handoff.to_booking == true` → phase becomes `booking`
5) Given `response_mode == "speak_first"` and `immediate_message != null` → speak happens before any tool execution for the turn
6) Given `response_mode == "tool_first"` → tool execution happens before any speak for the turn
7) Given `response_mode == "update_first"` → update tools run first, then we speak a single acknowledgement (e.g. “Got it”)

This test is the “wiring contract” for the deterministic loop described in the spec.

### Test 4.1 (expected): agent confirms callback number first, then proceeds
Write a text-mode behavioral test (LiveKit Agents testing helpers) that asserts:
- this test implements the spec’s “Golden path transcript (Milestone 1)” appendix
- first assistant message asks to confirm number (if SIP number exists)
- on “yes”, agent validates the number, checks/creates the customer, then proceeds to service collection
- expected early tool sequence: `validate_phone` → `check_customer` → (`register_new_customer` if needed) → enter the per-turn `get_case_status` loop

### Test 4.2 (edge): SIP number missing → agent asks for callback number
Simulate call metadata with no `sip.phoneNumber` and assert the agent requests a callback number and calls `validate_phone` after the user provides one.

### Test 4.3 (failure): backend tool call error → agent apologizes once and offers fallback
Force `BackendToolsClient` to raise and assert the agent says the standard fallback:
> “I’m having trouble connecting — please call back.”

### Manual smoke checklist (pre-cutover)
- [ ] Inbound call creates room + agent joins (explicit dispatch)
- [ ] Agent logs include `room_name` and (if available) `sip.phoneNumber`
- [ ] Backend `/vapi/tools` logs show matching `call_id == room_name`
- [ ] A full flow stores a service order in Postgres

---

## Test commands (during implementation)

Targeted while iterating:
```bash
pytest -q livekit_agent/tests/test_flow_controller_phase_transitions.py
pytest -q livekit_agent/tests/test_vapi_payload.py
pytest -q livekit_agent/tests/test_backend_tools_client.py
```

Before handoff:
```bash
pytest
```
