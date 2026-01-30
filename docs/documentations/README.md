# Repo Context Index (Codex)

> **Last Updated**: 2026-01-28  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** run a LiveKit voice agent with **OpenAI Realtime** + a provider-agnostic backend tools API (`POST /tools`).
- **Runtime:** `livekit_agent/` calls the backend tools server (`api_server/`) via `POST /tools` and follows tool results.
- **Default tests:** `pytest.ini` runs `livekit_agent/tests` only (API server tests exist but are not in default testpaths).

## Load order (recommended)
1. [`docs/documentations/repo-overview.md`](./repo-overview.md)
2. [`docs/documentations/livekit-agent.md`](./livekit-agent.md)
3. [`docs/documentations/api-server.md`](./api-server.md)

## Quick commands (copy/paste)
- Agent tests (default): `python -m pytest -q`
- API server tests (explicit): `python -m pytest -q api_server/tests`
- Run agent (console): `python -m livekit_agent.agent console`
- OpenAI Realtime audio smoke (no mic): `./scripts/run_openai_realtime_audio_smoke.sh`
- Customer lookup smoke (no mic; hits backend DB): `./scripts/run_openai_realtime_customer_lookup_smoke.sh --phone-number "305 555 0123"`
- Run tools backend (in-memory DB): `TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
- Docker (agent worker): `docker compose up --build`

## Contracts (what to assume is “true”)
- **Backend tools endpoint:** agent POSTs to `BACKEND_TOOLS_URL` (default ends with `/tools`) and expects a v2 response with `results[]` keyed by `tool_call_id`. See `docs/documentations/api-server.md`.
- **Auth required:** `POST /tools` requires `X-TOOLS-TOKEN` header (env `TOOLS_TOKEN`).
- **Tool args vs call_id:** backend uses `call.id` as the call ID (not a tool arg). See `docs/documentations/api-server.md`.
- **Tool param name:** backend expects `last_user_message` for `get_case_status`.

## Common gotchas (high-signal)
- `pytest.ini` only targets `livekit_agent/tests` (easy to miss failing `api_server/tests`).
- Backend derives `call_id` from the `/tools` payload (`call.id`), not from tool arguments.

## Module docs
- [`docs/documentations/squad-assistants.md`](./squad-assistants.md)
- [`docs/documentations/database-and-migrations.md`](./database-and-migrations.md)
- [`docs/documentations/testing-and-evals.md`](./testing-and-evals.md)
- [`docs/documentations/twilio-sms-confirmation.md`](./twilio-sms-confirmation.md)
- [`docs/documentations/tech-copilot-comparison.md`](./tech-copilot-comparison.md)
- [`docs/documentations/livekit-webrtc-debugging.md`](./livekit-webrtc-debugging.md)
- [`docs/documentations/debug.md`](./debug.md)
