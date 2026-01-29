# OpenAI Realtime + LiveKit agent

This repo runs a LiveKit voice agent using **OpenAI Realtime** as the conversation engine, plus a provider-agnostic backend tools API (`POST /tools`).

## Repo layout (two services, one repo)
- LiveKit agent service (deploy to LiveKit Cloud): `livekit_agent/`
- FastAPI tools backend service (deploy to Railway): `api_server/`
- Shared tool schemas (source of truth): `squad/assistants/*.json`

## What’s implemented
- Backend tools client (async) with typed errors: `livekit_agent/backend_tools_client.py`
- Provider-agnostic `/tools` v2 payload builder: `livekit_agent/tools_v2_payload.py`
- Tool schema loader from `squad/assistants/*.json` (+ local handoff tool schemas): `livekit_agent/tools.py`
- Deterministic flow controller (preflight callback gate + phase transitions + response_mode ordering): `livekit_agent/flow_controller.py`
- OpenAI Realtime session + agent: `livekit_agent/openai_realtime_session.py`, `livekit_agent/openai_realtime_agent.py`

## Run tests
```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./scripts/test_all.sh
```

## Run evals (offline)
Runs deterministic, offline conversation-level evals against a mocked backend (no network calls).

```bash
.venv/bin/python -m livekit_agent.evals
```

Helpful options:
- List scenarios: `.venv/bin/python -m livekit_agent.evals --list`
- Run one scenario: `.venv/bin/python -m livekit_agent.evals --scenario preflight_no_sip_speak_first`
- If you see `sysctlbyname('hw.logicalcpu') Operation not permitted`: add `NUM_CPUS=2` to your environment.

## Run the agent (Phase 4.1+)
Environment variables:
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `BACKEND_TOOLS_URL` (defaults to the dev URL in `squad/assistants/*.json`)
- `TOOLS_TOKEN` (shared secret header used by the agent to call `POST /tools`)
- `OPENAI_API_KEY`
- `AGENT_ENGINE` (optional: defaults to `openai_realtime`; set to `legacy` to use the old Deepgram+Cartesia pipeline)
- `AGENT_BACKEND_GUARDRAILS` (optional: defaults to `true`; set to `false` to let OpenAI manage the flow without calling `get_case_status` every turn)

Run in console mode (local, no telephony):
```bash
python -m livekit_agent.agent console
```

Run in dev mode (connects to LiveKit and joins dispatched rooms):
```bash
python -m livekit_agent.agent dev
```

Note: `GOOGLE_API_KEY`, `DEEPGRAM_API_KEY`, and `CARTESIA_API_KEY` are only required when using `AGENT_ENGINE=legacy`.

## Run the tools backend locally (debug)
The agent expects a `POST /tools` endpoint.

If you don't have Postgres configured yet, you can run a non-durable in-memory backend:

```bash
TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 .venv/bin/python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

## Deploy the tools backend to Railway
This repo includes separate Dockerfiles for the agent vs backend:
- Agent: `Dockerfile`
- Backend: `Dockerfile.backend` (uses `requirements.backend.txt`)

In your Railway backend service, set the Dockerfile path to `Dockerfile.backend` and ensure `DATABASE_URL` is set.

## Deploy / debug with Docker
This is the easiest way to run the agent with consistent ports, structured logs, and scrapeable metrics.

Run:
```bash
docker compose up --build
```

Endpoints (from `docker-compose.yml`):
- Health check: `http://localhost:8081/`
- Worker info: `http://localhost:8081/worker`
- Prometheus metrics: `http://localhost:9090/metrics`

Useful env vars:
- `LOG_LEVEL=DEBUG` to increase verbosity
- `LOG_PII=1` to disable call-id masking in backend tool logs (not recommended for production)
- `LIVEKIT_AGENT_NAME=...` to enable explicit dispatch
