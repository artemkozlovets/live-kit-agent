# API Server (Codex Context)

> **Last Updated**: 2026-01-24  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `api_server/` is a FastAPI app that implements a **Vapi-compatible tools backend**.
- Main contract surface:
  - `POST /vapi/tools` → returns `{"results":[...]}` (plus optional `destination` for handoffs).
  - `POST /vapi/assistant-request` → returns `{squadId, squadOverrides:{variableValues:{...}}}` for Vapi phone routing.
- For Railway deploys in this monorepo, use `Dockerfile.backend` (installs `requirements.backend.txt`).

## Entry points / key files
- FastAPI app wiring: `api_server/server/fastapi_app.py`
- Vapi endpoints: `api_server/vapi/router.py`
- Tool registry + dispatch: `api_server/vapi/dispatcher.py`
- Tool payload parsing helpers: `api_server/vapi/tool_call_parsing.py`
- Per-call in-memory state: `api_server/vapi/session_store.py`
- `get_case_status` stack:
  - I/O + orchestration: `api_server/vapi/handlers/case_status.py`
  - Pure case state builder: `api_server/vapi/case_status.py`

## HTTP endpoints (contracts)

### `POST /vapi/tools`
- Handler: `api_server/vapi/router.py`
- Input (minimum assumptions):
  - Request JSON contains `message` object.
  - Tool calls are in `message.toolCallList` or `message.toolCalls`.
  - Each tool call can be:
    - OpenAI-style: `{"id": "...", "function": {"name": "...", "arguments": "<json string>"}}`
    - Flat: `{"id": "...", "name": "...", "arguments": {...}}`
- Call identity:
  - Call id is read from `message.call.id` (see `api_server/vapi/tool_call_parsing.py`).
- Output:
  - `{"results":[{"toolCallId":"...","result":"<json string>"}]}`
  - For handoff tools, also set `destination` (Vapi uses this to transfer to another assistant).

### `POST /vapi/assistant-request`
- Handler: `api_server/vapi/router.py` → `api_server/vapi/assistant_request.py`
- Behavior:
  - Only responds when `message.type == "assistant-request"`.
  - Extracts caller number and looks up an existing customer by phone (if DB configured).
  - Returns a `squadId` and `squadOverrides.variableValues` (e.g., `customerName`, `customerPhone`, `customerId`, `isKnownCustomer`).

### Other HTTP endpoints (non-Vapi)
These are additional routes (useful for debugging / legacy webhooks):
- `POST /inbound` (customer lookup): `api_server/server/routers/customer.py`
- `POST /newCustomer` (create customer): `api_server/server/routers/customer.py`
- `POST /updateNumber` (update phone): `api_server/server/routers/customer.py`
- `POST /checkVin`, `POST /storeUnit`: `api_server/server/routers/unit.py`
- `POST /storeServiceOrder`: `api_server/server/routers/service_order.py`
- `POST /phoneVerify`, `POST /validateVIN`: `api_server/server/routers/validation.py`

## Tool dispatch (source of truth)
- Registry is a dict: `api_server/vapi/dispatcher.py` (`TOOL_REGISTRY`).
- Dispatch entrypoint: `dispatch_tool_call(...)` in the same file.

Tools currently registered include:
- customer: `validate_phone`, `check_customer`, `register_new_customer`, `update_customer`
- vehicle: `validate_vin`, `check_vin_database`
- session: `add_service`, `confirm_services`, `get_session_summary`
- booking/order: `store_service_order`, `update_service_order`, `send_confirmation_sms`
- state: `get_case_status`

## Session state (per call)
- There is a singleton `SessionStore` used across requests:
  - `api_server/vapi/router.py` creates a module-level store.
  - `SessionStore` is dict-backed and keyed by `call_id`.
- This is an MVP constraint (single-instance); it is not durable.

## `get_case_status` (the “call brain”)
`get_case_status` returns:
- Base case state (customer/service/booking summary + missing fields)
- Message-aware guidance (`response_mode`, `immediate_message`, `then_action`)

Key facts:
- Input arg of interest: `last_user_message` (tool arguments).
- Backend also reads call context from the payload (`call_id`, caller phone, overrides, etc.).
- Optional behaviors are gated by env flags (Gemini classification/extraction/corrections vs fast extractor).

## DB wiring (env-driven)
- Interface + selection: `api_server/server/dependencies.py`
- Env vars:
  - `DATABASE_URL` → Postgres implementation (`psycopg2`)
  - `USE_IN_MEMORY_DB=1` → in-memory DB
- Gotcha: `get_database_client()` currently creates a new `psycopg2.connect(...)` connection when `DATABASE_URL` is set (no pooling).

## Run locally (copy/paste)
- Start API server (in-memory DB): `USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
- Timing logs for tool calls: set `VAPI_TOOLS_LOG_TIMING=1`

## Gotchas (high-signal)
- Tool calls can arrive under `toolCallList` or `toolCalls`, and arguments can be dict or JSON string → always use `api_server/vapi/tool_call_parsing.py`.
- Some configs include `call_id` as a tool arg; backend uses `message.call.id` as canonical call id.

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/database-and-migrations.md`
- `docs/documentations/squad-assistants.md`
