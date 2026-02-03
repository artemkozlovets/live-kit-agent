# API Server (Codex Context)

> **Last Updated**: 2026-02-03  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** provide a provider-agnostic tools backend for the LiveKit agent.
- **Primary endpoint:** `POST /tools` (v2 contract + auth).
- **Auth:** requires header `X-TOOLS-TOKEN` matching env `TOOLS_TOKEN`.
- **Legacy:** `POST /vapi/tools` is removed (404).
- **How to verify:** `./scripts/test_all.sh`

## Key files (start here)
- FastAPI app wiring: `api_server/server/fastapi_app.py`
- `/tools` v2 endpoint + auth + dispatch: `api_server/tools/router.py`
- Tool registry + dispatch: `api_server/vapi/dispatcher.py`
- Tool payload parsing helpers: `api_server/vapi/tool_call_parsing.py`
- Session store (per-call in-memory dict): `api_server/vapi/session_store.py`
- `get_case_status` stack:
  - Orchestration + guardrails: `api_server/vapi/handlers/case_status.py`
  - Pure case state builder: `api_server/vapi/case_status.py`

## State + scaling (important)
This backend currently uses an **in-memory** per-call session store keyed by `call.id`.

Implications:
- If the backend restarts mid-call, it will “forget” prior turns and may re-ask for phone/name/address.
- If you run **multiple replicas** without a shared store (ex: Redis) and sticky routing, different turns of the same call can hit different replicas and lose continuity.

## `POST /tools` (v2 contract)

### Request (minimum)
```json
{
  "call": { "id": "lk-room-name-or-call-id" },
  "tool_calls": [
    {
      "id": "tool-call-uuid",
      "name": "get_case_status",
      "arguments": { "last_user_message": "Hello", "expected_field": null }
    }
  ]
}
```

Notes:
- `call.id` is the canonical call correlation ID.
- `tool_calls[].arguments` must be a JSON object (not a JSON string).
- Optional parent structures are supported:
  - `customer.number` (raw caller ID)
  - `call.customer.number` (confirmed callback number)
  - `assistant.variable_values` (known-customer prefill)

### Response
```json
{
  "results": [
    {
      "tool_call_id": "tool-call-uuid",
      "name": "get_case_status",
      "ok": true,
      "result": { "current_phase": "customer_intake" }
    }
  ]
}
```

Notes:
- Per-tool failures return `ok: false` and an `error` object (HTTP stays `200` when the request is valid).
- Request-shape/auth failures use HTTP errors (`400`/`401`).

### Auth
- Required header: `X-TOOLS-TOKEN: <secret>`
- Backend env: `TOOLS_TOKEN`
- Behavior:
  - Missing/invalid header → `401`
  - Missing `TOOLS_TOKEN` env → `500` (deploy misconfig)

## Dispatch + handlers
- `api_server/tools/router.py` validates the v2 request and then reuses the existing dispatcher:
  - `api_server.vapi.dispatcher.dispatch_tool_call(...)`
- The v2 router builds a v1-compatible `message_payload` shim for handler reuse:
  - Preserves `call`, `customer`, and `assistant`
  - Maps `assistant.variable_values` → internal `assistantOverrides.variableValues`
  - Tags payload with `_tools_api_version = 2` so handlers can enforce “realtime mode” constraints

## Booking safety (must-not-break)
- `POST /tools` enforces **no booking without explicit confirmation**:
  - If `store_service_order` is called before confirmation, the router returns:
    - `ok: false`, `error.code = "booking_not_confirmed"`

## Local observability (optional)
- If env `LOCAL_OBSERVABILITY_DIR` is set, `POST /tools` appends one JSON line per request:
  - `backend.tools.jsonl`

## Run locally (copy/paste)
- Start backend (in-memory DB):
  - `TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`

## Verification
- Happy path (all tests): `./scripts/test_all.sh`
- Backend only: `.venv/bin/python -m pytest -q api_server/tests`
- Edge case: missing auth token:
  - `.venv/bin/python -m pytest -q api_server/tests -k test_tools_v2_missing_token_returns_401`
- Failure case: legacy endpoint removed:
  - `.venv/bin/python -m pytest -q api_server/tests -k test_vapi_tools_removed_returns_404`

## Related docs
- `docs/specs/openai_realtime-spec.md`
- `docs/documentations/livekit-agent.md`
- `docs/documentations/testing-and-evals.md`
