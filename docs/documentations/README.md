# Repo Context Index (Codex)

> **Last Updated**: 2026-01-25  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** migrate the voice runtime from Vapi to LiveKit, while keeping a Vapi-shaped backend tool contract (`POST /vapi/tools`).
- **Runtime:** `livekit_agent/` calls the backend tools server (`api_server/`) and follows tool results.
- **Default tests:** `pytest.ini` runs `livekit_agent/tests` only (API server tests exist but are not in default testpaths).

## Load order (recommended)
1. [`docs/documentations/repo-overview.md`](./repo-overview.md)
2. [`docs/documentations/livekit-agent.md`](./livekit-agent.md)
3. [`docs/documentations/api-server.md`](./api-server.md)

## Quick commands (copy/paste)
- Agent tests (default): `python -m pytest -q`
- API server tests (explicit): `python -m pytest -q api_server/tests`
- Offline evals: `python -m livekit_agent.evals`
- Run agent (console): `python -m livekit_agent.agent console`
- Run tools backend (in-memory DB): `USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
- Docker (agent worker): `docker compose up --build`

## Contracts (what to assume is “true”)
- **Backend tools endpoint:** agent POSTs to `BACKEND_TOOLS_URL` and expects a Vapi-style response with `results[]` keyed by `toolCallId`. See `docs/documentations/livekit-agent.md`.
- **Tool args vs call_id:** backend uses `message.call.id` as the call ID (not a tool arg). See `docs/documentations/api-server.md`.
- **Tool param name:** current backend expects `last_user_message` for `get_case_status`. Some exports use `user_message` (not source of truth). See `docs/documentations/vapi-export.md`.

## Common gotchas (high-signal)
- `pytest.ini` only targets `livekit_agent/tests` (easy to miss failing `api_server/tests`).
- `squad/assistants/service_collection.json` includes a `call_id` tool param, but backend derives call ID from the payload.
- `vapi_export/` is historical; don’t treat it as current tool schema.

## Module docs
- [`docs/documentations/squad-assistants.md`](./squad-assistants.md)
- [`docs/documentations/database-and-migrations.md`](./database-and-migrations.md)
- [`docs/documentations/vapi-export.md`](./vapi-export.md)
- [`docs/documentations/testing-and-evals.md`](./testing-and-evals.md)
- [`docs/documentations/livekit-webrtc-debugging.md`](./livekit-webrtc-debugging.md)
- [`docs/documentations/debug.md`](./debug.md)
