# Repo Overview (Codex)

> **Last Updated**: 2026-01-30  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** run a LiveKit voice runtime with **OpenAI Realtime** + a provider-agnostic tools API (`POST /tools`).
- **Runtime:** `livekit_agent/` (agent worker) ⇄ `api_server/` (tools backend).
- **Specs/config:** `squad/assistants/` is the source of tool schemas that the agent loads.
- **DB:** schema changes live in `migrations/`.

## Scope: OpenAI Realtime-only
This repo intentionally supports **one** conversation engine:
- ✅ OpenAI Realtime (default and only)
- ❌ Legacy STT/TTS pipelines (removed)
- ❌ Gemini networked extraction/classification (removed; `get_case_status` is deterministic)
- ❌ Offline eval suite (removed)
- ❌ `vapi_export/` historical artifacts (removed)

## Runtime flow (happy path)
1. LiveKit starts the agent worker (`livekit_agent/agent.py`).
2. Agent uses **OpenAI Realtime**.
3. Each user turn:
   - agent calls `get_case_status(last_user_message=...)` via `POST /tools`
   - backend returns the current state + guardrails (missing fields, next action)
4. Backend (`api_server`) returns tool results in v2 format: `{"results":[{"tool_call_id":"...","ok":true,"result":{...}}]}`.

## Key contracts (do not guess)

### Backend tools response
- Response JSON has `results: list`.
- Each result entry includes `tool_call_id` matching the request tool call id.
- `result` is a JSON object (dict).
- `POST /tools` requires header `X-TOOLS-TOKEN` matching env `TOOLS_TOKEN`.

### Call identity
- Agent call id is usually the LiveKit room name (`ctx.room.name`).
- API server derives call id from `call.id` in the tools v2 payload.

## Repo map (where things live)
- `livekit_agent/` — LiveKit Agents runtime + `/tools` v2 client + guardrails.
- `api_server/` — FastAPI server (implements `POST /tools`).
- `squad/assistants/` — assistant JSON + `.prompt.md` instructions (also used for tool schema loading).
- `migrations/` — SQL migrations (Postgres).
- `docs/instructions/` — operational runbooks (logs, Railway CLI, etc.).

## Primary entry points (start here when debugging)
- Agent worker CLI + orchestration: `livekit_agent/agent.py`
- Agent→backend HTTP + tools v2 payload builder: `livekit_agent/backend_tools_client.py`, `livekit_agent/tools_v2_payload.py`
- Tool schemas loader: `livekit_agent/tools.py`
- API server app: `api_server/server/fastapi_app.py`
- Tools v2 endpoint: `api_server/tools/router.py`
- Tool registry/dispatch: `api_server/vapi/dispatcher.py`
- DB wiring + env switching: `api_server/server/dependencies.py`

## Run/verify (copy/paste)
- Agent tests (default): `python -m pytest -q`
- All tests (agent + backend): `./scripts/test_all.sh`
- Run agent (console): `python -m livekit_agent.agent console`
- OpenAI Realtime audio smoke (no mic): `./scripts/run_openai_realtime_audio_smoke.sh`
- Run tools backend (in-memory DB): `TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
- Docker (agent worker): `docker compose up --build`

## Gotchas (high-signal)
- `pytest.ini` only runs `livekit_agent/tests` by default (API server tests are separate).
- `docker-compose.yml` currently runs the agent worker service (not the API server).

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/documentations/database-and-migrations.md`
