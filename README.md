# Vapi → LiveKit migration (Milestone 1)

This repo contains the Milestone 1 foundations for migrating the voice runtime from Vapi to LiveKit while keeping the backend tool contract (`POST /vapi/tools`) unchanged.

## What’s implemented
- Vapi-shaped tool-call payload builder: `livekit_agent/vapi_payload.py`
- Backend tools client (async) with typed errors: `livekit_agent/backend_tools_client.py`
- Tool schema loader from `squad/assistants/*.json` (+ local handoff tool schemas): `livekit_agent/tools.py`
- Deterministic flow controller (preflight callback gate + phase transitions + response_mode ordering): `livekit_agent/flow_controller.py`

## Run tests
```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
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
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_STT_MODEL` (optional, defaults to `flux-general-en`)
- `DEEPGRAM_EAGER_EOT_THRESHOLD` (optional, defaults to `0.4`)
- `CARTESIA_API_KEY` (optional: `CARTESIA_VOICE_ID`, `CARTESIA_TTS_MODEL`, `CARTESIA_SPEED`, `CARTESIA_TEXT_PACING`)
- `GOOGLE_API_KEY` (optional: `GOOGLE_LLM_MODEL`, defaults to `gemini-2.5-flash`)

Run in console mode (local, no telephony):
```bash
python -m livekit_agent.agent console
```

Run in dev mode (connects to LiveKit and joins dispatched rooms):
```bash
python -m livekit_agent.agent dev
```

Note: if `GOOGLE_API_KEY` is not set, the agent falls back to a simple `then_action` string parser (useful for local testing, not production-grade).

## Run the tools backend locally (debug)
The agent expects a Vapi-compatible `POST /vapi/tools` endpoint.

If you don't have Postgres configured yet, you can run a non-durable in-memory backend:

```bash
USE_IN_MEMORY_DB=1 .venv/bin/python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

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
