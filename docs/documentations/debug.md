# Debugging (Single Source of Truth)

> **Last Updated**: 2026-01-25  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## Big picture
This repo has **two services** (LiveKit agent + tools backend). Debugging is fastest when you **isolate the layer**:
- **Web client** (browser / WebRTC connectivity)
- **Agent runtime** (LiveKit Cloud worker logs)
- **Backend tools** (`POST /vapi/tools` on Railway or local FastAPI)

## The one ID that ties everything together
In this repo, **call_id == LiveKit room name**:
- Agent call id: `ctx.room.name`
- Backend call id: `message.call.id` (sent by the agent in tool-call payloads)

Practical impact:
- Use the **room name** when correlating agent logs, backend tool logs, and session reports.
- The session report endpoint is keyed by `{room_name}`.

## Quick triage (start here)
1. **Is it web connectivity?**
   - Try the same `serverUrl` + token in LiveKit Meet.
   - If Meet fails, fix URL/token/network first (not the agent code).
2. **Is it media-only?**
   - Turn on LiveKit JS SDK logs and collect a WebRTC dump.
3. **Is it end-to-end agent behavior?**
   - Check LiveKit agent logs and Railway tool logs side-by-side.
4. **Do you need "agent insights" data without opening the UI?**
   - Use the **Session report exporter** (programmatic observability) below.

## LiveKit Cloud quick checks (no UI)
Validate "is the agent deployed / configured / running" before deeper debugging:

```bash
# Is the CLI pointed at the right project/agent?
cat livekit.toml
lk project list
lk agent status

# Secrets are present (names only; values not printed):
lk agent secrets

# Deployment history:
lk agent versions
```

If you set `LIVEKIT_AGENT_NAME`, you turned on explicit dispatch:
```bash
# Create a dispatch (or list dispatches in a room)
lk dispatch create --agent-name "<agent-name>" --room "<room-name>" --metadata '{"user_id":"123"}'
lk dispatch list "<room-name>"
```

If you suspect the room exists / participants are present:
```bash
lk room list
lk room participants list "<room-name>"
```

## Programmatic observability (no UI)
This repo supports a lightweight “session report” pipeline so you can fetch a
structured post-call artifact without opening LiveKit Cloud.

### How it works
- At session end, the agent calls `ctx.make_session_report()` (LiveKit Agents SDK).
- If `SESSION_REPORTS_URL` is set, the agent POSTs `{room_name, report}` to your backend.
- The backend stores the latest report per room name and exposes it over HTTP.

Important behavior:
- The report is published **when the session ends** (usually when the room closes / participants leave).
  If you fetch during an active call, you may see `404` until the call ends.

### Configure (production)
Agent (LiveKit Cloud agent secrets):
- `SESSION_REPORTS_URL=https://<your-railway-domain>/observability/session-report`
- `SESSION_REPORTS_TOKEN=<shared bearer token>` (recommended)

Backend (Railway env):
- `SESSION_REPORTS_TOKEN=<same shared bearer token>` (recommended)

CLI helpers (no UI):
```bash
# LiveKit Cloud agent secrets (restarts the agent):
lk agent update-secrets \
  --secrets "SESSION_REPORTS_URL=https://<your-railway-domain>/observability/session-report" \
  --secrets "SESSION_REPORTS_TOKEN=<shared bearer token>"

# Railway service variables (triggers a deploy unless you pass --skip-deploys):
railway variables \
  --service "Call-agent" --environment development \
  --set "SESSION_REPORTS_TOKEN=<shared bearer token>"
```

Notes:
- If `SESSION_REPORTS_TOKEN` is unset on the backend, the endpoint is unauthenticated.
- Storage is **in-memory** (MVP). If Railway restarts, reports are lost.

### Endpoints
Backend endpoints (FastAPI):
- `POST /observability/session-report` (ingest; called by agent)
- `GET /observability/session-report?limit=20` (list recent reports)
- `GET /observability/session-report/{room_name}` (fetch report)

### Find the room name (no UI)
If you don't already know the room name:
- If you control the web call, you usually picked it when minting the token.
- Otherwise, list recent reports:
```bash
curl -sS \
  -H "Authorization: Bearer $SESSION_REPORTS_TOKEN" \
  "https://<your-railway-domain>/observability/session-report?limit=20"
```

### Fetch the latest report for a room
```bash
curl -sS \
  -H "Authorization: Bearer $SESSION_REPORTS_TOKEN" \
  "https://<your-railway-domain>/observability/session-report/<room_name>"
```

Common responses:
- `200`: returns `{ room_name, report, received_at_unix_s }`
- `401`: token mismatch / missing `Authorization` header
- `404`: no report stored (agent didn’t publish yet, wrong room name, or backend restarted)

### Local smoke test (no LiveKit required)
Run backend:
```bash
USE_IN_MEMORY_DB=1 SESSION_REPORTS_TOKEN=test-token \
  python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

Ingest a fake report:
```bash
curl -sS -X POST "http://127.0.0.1:8000/observability/session-report" \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{"room_name":"room-123","report":{"hello":"world"}}'
```

Fetch it back:
```bash
curl -sS "http://127.0.0.1:8000/observability/session-report/room-123" \
  -H "Authorization: Bearer test-token"
```

Local agent note:
- If you run the agent via `python -m livekit_agent.agent dev|start`, just export `SESSION_REPORTS_URL`
  and `SESSION_REPORTS_TOKEN` in your shell (or in `.env`) before starting.
- If you run via Docker Compose, you must pass those env vars into the container (the current
  `docker-compose.yml` doesn’t include them yet).

### Where this lives in the repo
- Agent publisher: `livekit_agent/session_report_publisher.py`
- Agent wiring (`on_session_end`): `livekit_agent/agent.py`
- Backend endpoint: `api_server/observability/router.py`

## LiveKit Cloud observability (UI)
LiveKit Cloud also provides built-in **Agent insights** (traces/transcripts/logs/recordings).
That is configured in LiveKit Cloud project settings (Data & privacy → Agent observability).

## Logs: "full power" mode (production)
LiveKit Cloud can forward agent runtime logs to external systems for retention/searching
(recommended once you care about history or multiple replicas).

Your options include Datadog, CloudWatch, Sentry, and New Relic.

Example (Sentry):
```bash
lk agent update-secrets --secrets "SENTRY_DSN=<your dsn>"
```

Important:
- `lk agent logs` shows logs from the **newest agent server instance only**.
  If you ever scale replicas, you should enable log forwarding to avoid missing logs.

Also useful:
```bash
# Build logs for the currently deployed version:
lk agent logs --log-type build
```

## Traces + metrics (advanced, optional)
If you need more than logs and session reports:
- LiveKit Agents can export spans to any OpenTelemetry backend (Python).
- The SDK emits `metrics_collected` events you can forward to your metrics stack.

This repo does not wire those exports by default, but it's the next step if you
want "real observability" outside the LiveKit UI.

## Web (browser) debugging
Use the dedicated WebRTC guide for the full flow:
- `docs/documentations/livekit-webrtc-debugging.md`

High-signal steps from that guide:
- Join the room in LiveKit Meet to isolate URL/token issues.
- Run the LiveKit connection test for TURN/ICE visibility.
- Enable JS SDK logs with `setLogLevel("debug")`.
- Capture `chrome://webrtc-internals` (or `about:webrtc` in Firefox).

## Agent runtime (LiveKit Cloud)
Tail the worker logs:
```bash
lk agent logs --log-type deploy
```
Look for:
- `AgentSession error`
- `AgentSession closing`

## Backend tools (Railway)
Start with low-noise log filters:
```bash
railway logs --lines 200 --filter "@level:error"
railway logs --lines 200 --filter "/vapi/tools"
```
If you need a time-bounded slice (best for a single call):
```bash
python -m squad.scripts.debug_call --railway-only --minutes 10
```
Docs:
- `docs/instructions/pull-railway-logs.md`
- `docs/instructions/efficient-logs-for-codex.md`

## Local debugging knobs
These env vars increase signal or timing detail:
- `LOG_LEVEL=DEBUG` (agent + backend verbosity)
- `LOG_PII=1` (disables masking of call IDs/phone numbers; avoid in prod)
- `VAPI_TOOLS_LOG_TIMING=1` (tools timing logs in API server)
- `SESSION_REPORTS_URL=...` (agent: enables session report POST on session end)
- `SESSION_REPORTS_TOKEN=...` (agent + backend: bearer auth for session report endpoint)

Agent behavior gotchas:
- The agent won't call `get_case_status` until preflight completes (callback number validated + customer check).
- For web calls (no SIP), set `SKIP_CALLBACK_PREFLIGHT=1` so the agent can proceed.

Local backend (in-memory DB) for quick reproductions:
```bash
USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

## Deterministic repro (fast, no LiveKit/Railway required)
When debugging logic (not networking), use tests/evals:

```bash
# Agent unit/integration-ish tests (default pytest target):
python -m pytest -q

# Full repo tests (agent + api_server):
./scripts/test_all.sh

# Offline eval scenarios (no network):
python -m livekit_agent.evals --list
python -m livekit_agent.evals --scenario preflight_no_sip_speak_first
```

## When asking for help (keep it short)
Provide:
- `serverUrl` (non-secret) + token **payload** (redact signature)
- Browser + OS + VPN/corp network info
- LiveKit connection test result
- LiveKit SDK logs + WebRTC dump
- Railway log snippet (filtered) or agent log excerpt

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/instructions/debug-livekit-agent-silence.md`
