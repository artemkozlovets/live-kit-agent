# Repo Overview (Codex)

> **Last Updated**: 2026-01-24  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** migrate the voice runtime from Vapi → LiveKit, while keeping a **Vapi-shaped tools contract** (`POST /vapi/tools`).
- **Runtime:** `livekit_agent/` (agent worker) ⇄ `api_server/` (tools backend).
- **Specs/config:** `squad/assistants/` is the source of tool schemas that the agent loads.
- **DB:** schema changes live in `migrations/`.
- **Exports:** `vapi_export/` is historical reference (not source of truth).

## Runtime flow (happy path)
1. LiveKit starts the agent worker (`livekit_agent/agent.py`).
2. Agent preflight: collect callback number → call backend tools:
   - `validate_phone`
   - `check_customer`
3. Each user turn:
   - agent calls `get_case_status(last_user_message=...)`
   - agent follows `response_mode` + `immediate_message` + `then_action` from backend.
4. Backend (`api_server`) returns tool results in Vapi format: `{"results":[{"toolCallId":"...","result":"<json>"}]}`.

## Key contracts (do not guess)

### Backend tools response
- Response JSON has `results: list`.
- Each result entry includes `toolCallId` matching the request tool call id.
- `result` is usually a JSON string (backend does `json.dumps(...)`), but the agent also tolerates a dict.

### Call identity
- Agent call id is usually the LiveKit room name (`ctx.room.name`).
- API server derives call id from `message.call.id` in the incoming Vapi payload.

## Repo map (where things live)
- `livekit_agent/` — LiveKit Agents runtime + adapter to Vapi-shaped tools.
- `api_server/` — FastAPI server (implements `/vapi/tools` + `/vapi/assistant-request`).
- `squad/assistants/` — assistant JSON + `.prompt.md` instructions (also used for tool schema loading).
- `migrations/` — SQL migrations (Postgres).
- `vapi_export/` — exported snapshots from Vapi (reference only).
- `docs/instructions/` — operational runbooks (logs, Railway CLI, etc.).

## Primary entry points (start here when debugging)
- Agent worker CLI + orchestration: `livekit_agent/agent.py`
- Agent→backend HTTP + Vapi payload builder: `livekit_agent/backend_tools_client.py`, `livekit_agent/vapi_payload.py`
- Tool schemas loader: `livekit_agent/tools.py`
- API server app: `api_server/server/fastapi_app.py`
- Vapi endpoints: `api_server/vapi/router.py`
- Tool registry/dispatch: `api_server/vapi/dispatcher.py`
- DB wiring + env switching: `api_server/server/dependencies.py`

## Run/verify (copy/paste)
- Agent tests (default): `python -m pytest -q`
- All tests (agent + backend): `./scripts/test_all.sh`
- Offline evals: `python -m livekit_agent.evals`
- Run agent (console): `python -m livekit_agent.agent console`
- Run tools backend (in-memory DB): `USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
- Docker (agent worker): `docker compose up --build`

## Gotchas (high-signal)
- `pytest.ini` only runs `livekit_agent/tests` by default (API server tests are separate).
- Some Vapi exports use `user_message` while current backend expects `last_user_message` for `get_case_status`.
- `docker-compose.yml` currently runs the agent worker service (not the API server).

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/documentations/database-and-migrations.md`
