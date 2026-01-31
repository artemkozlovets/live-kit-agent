# Debugging (Single Source of Truth)

> **Last Updated**: 2026-01-31  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## Big picture
This repo has **two services** (LiveKit agent + tools backend). Debugging is fastest when you **isolate the layer**:
- **Web client** (browser / WebRTC connectivity)
- **Agent runtime** (LiveKit Cloud worker logs)
- **Backend tools** (`POST /tools` on Railway or local FastAPI)

### Automation expectation (for Codex)
If a CLI command or quick check is needed, **run it directly** and report the result. Avoid asking the user to run commands unless you truly can't.

## The one ID that ties everything together
In this repo, **call_id == LiveKit room name**:
- Agent call id: `ctx.room.name`
- Backend call id: `call.id` (sent by the agent in tool-call payloads)

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

## Choose your debug environment (fastest to slowest)
Pick the environment that isolates the layer you are testing. This cuts noise and
makes logs easier to interpret.

### 1) Local console (agent + backend on your machine)
**Best for:** logic bugs, tools flow, and fast iteration.

Pros:
- Most complete logs, in one place (JSONL + tool traces + session reports).
- Fast iteration (no deployment or LiveKit config dependencies).
- Deterministic repro with `./scripts/run_local_audio_console.sh`.

Cons:
- Does not catch LiveKit Cloud config issues (secrets, dispatch, scaling).
- Does not reproduce SIP/phone call edge cases.

### 2) LiveKit Cloud + Meet (remote web calls)
**Best for:** real deployment validation without SIP complexity.

Pros:
- Real agent deployment; validates LiveKit secrets and runtime.
- Fewer moving parts than PSTN.
- Room name == call_id lets you correlate agent + Railway logs.

Cons:
- Logs split across LiveKit Cloud and Railway.
- `lk agent logs` only shows newest instance (forward logs if scaled).
- Repro is slower and dependent on browser/network state.

### 3) LiveKit Cloud + Telephony (phone/PSTN calls)
**Best for:** validating PSTN routing, caller ID, and speak-first timing.

Pros:
- Only way to verify SIP routing + caller ID behavior.
- Catches dispatch rule issues Meet will never show.

Cons:
- Most moving parts (phone number -> SIP -> dispatch -> room -> agent -> tools).
- Timing-sensitive: caller hears dial tone until agent publishes audio.
- Hardest to reproduce and correlate.

### Recommended order (fastest to isolate)
1) **Local console** to confirm tool loop + agent behavior.
2) **Meet** to validate LiveKit Cloud config without SIP.
3) **Telephony** only when the issue is PSTN-specific.

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
- Storage:
  - **Postgres** when `DATABASE_URL` is set (Railway prod) → durable.
  - **In-memory** otherwise (local dev/tests) → lost on restart.

Migration required for Postgres:
- Apply `migrations/002_add_session_reports.sql` to your Railway Postgres database.

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

## Voice + turn-taking observability (Realtime)
This repo is currently **good at plumbing checks** (agent deployed, joins room, backend `/tools` calls succeed),
but voice issues need **turn-level artifacts** to debug reliably:
- The agent "talks to itself" (echo / phantom turns).
- The first greeting gets cut off (barge-in / false interruption).
- Turn detection feels laggy or cancels responses.

### Option 1: Session reports (post-call, no UI)
Session reports are the highest signal per call because they include:
- events (agent_state, user_state, transcripts, interruptions)
- chat history (user + assistant messages with `interrupted: true/false`)
- Realtime metrics (including `ttft`)

If `SESSION_REPORTS_URL` is configured on the agent (LiveKit Cloud), the backend stores reports under:
- `GET /observability/session-report?limit=20`
- `GET /observability/session-report/{room_name}`

Helper scripts:
```bash
# Enable publishing from the LiveKit Cloud agent (restarts agent):
./scripts/lk_agent_session_reports_on.sh "$LIVEKIT_AGENT_ID" "https://call-agent-development.up.railway.app/observability/session-report"

# Fetch the last 5 calls (redacted by default):
./scripts/fetch_session_reports.py --url "https://call-agent-development.up.railway.app/observability/session-report" --limit 5

# Disable publishing:
./scripts/lk_agent_session_reports_off.sh "$LIVEKIT_AGENT_ID"
```

Notes:
- Reports appear only after the call ends.
- `--pii` prints full user/assistant messages (treat as sensitive).

### Option 2: Realtime wire debug (short window; lots of output)
Use this when you need raw Realtime websocket events (turn detection + generation lifecycle).

Helper scripts:
```bash
# Enable (restarts agent):
./scripts/lk_agent_realtime_debug_on.sh "$LIVEKIT_AGENT_ID"

# Disable:
./scripts/lk_agent_realtime_debug_off.sh "$LIVEKIT_AGENT_ID"
```

### Option 3: Repo-native voice logs (recommended long-term)
Enable `VOICE_DEBUG=1` on the agent to log high-signal session events at INFO:
- `agent_state_changed`, `user_state_changed`
- `user_input_transcribed` (final transcript redacted unless `LOG_PII=1`)
- `speech_created` + `speech_done`
- `metrics_collected` (Realtime `ttft`, token counts)
- `function_tools_executed` (tool names + failures)
- backend tool timing (`VOICE_DEBUG backend_tool_*` in `livekit-agent.backend-tools`)

Helper scripts:
```bash
# Enable (restarts agent):
./scripts/lk_agent_voice_debug_on.sh "$LIVEKIT_AGENT_ID"

# Disable:
./scripts/lk_agent_voice_debug_off.sh "$LIVEKIT_AGENT_ID"
```

PII defaults:
- VOICE_DEBUG logs redact transcripts by default.
- Set `LOG_PII=1` only for short reproductions.

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

### Prompt / behavior checks
- OpenAI Realtime runtime instructions live in `livekit_agent/openai_realtime_agent.py`
  (the `instructions=...` string). Changes in `squad/assistants/*.prompt.md` do **not**
  affect the Realtime agent.

## Backend tools (Railway)
Start with low-noise log filters:
```bash
railway logs --lines 200 --filter "@level:error"
railway logs --lines 200 --filter "/tools"
```
If you need timestamps (best for correlating to a specific LiveKit room):
```bash
railway logs --lines 200 --filter "@level:error" --json
railway logs --lines 200 --filter "/tools" --json
```
Docs:
- `docs/instructions/pull-railway-logs.md`
- `docs/instructions/efficient-logs-for-codex.md`

## Local debugging knobs
These env vars increase signal or timing detail:
- `LOG_LEVEL=DEBUG` (agent + backend verbosity)
- `LOG_PII=1` (disables masking of call IDs/phone numbers; avoid in prod)
- `LK_OPENAI_DEBUG=1` (agent: logs OpenAI Realtime websocket events; high-volume; likely contains PII)
- `VOICE_DEBUG=1` (agent: structured voice/turn logs; transcripts redacted unless `LOG_PII=1`)
- `VAPI_TOOLS_LOG_TIMING=1` (tools timing logs in API server; legacy name)
- `SESSION_REPORTS_URL=...` (agent: enables session report POST on session end)
- `SESSION_REPORTS_TOKEN=...` (agent + backend: bearer auth for session report endpoint)
- `LOCAL_OBSERVABILITY_DIR=...` (local: persist logs + session reports to disk)
- `AGENT_BACKEND_GUARDRAILS=false` (agent: OpenAI-first; skips per-turn `get_case_status`)
- `OPENAI_REALTIME_VOICE=...` (agent: optional voice selection)

When `LOCAL_OBSERVABILITY_DIR` is set:
- Backend writes:
  - `backend.log.jsonl` (structured logs)
  - `backend.tools.jsonl` (one JSONL event per `/tools` request with tool names + result keys)
  - `session-reports/*.json` (persisted session reports ingested via `POST /observability/session-report`)
- Agent writes:
  - `agent.log.jsonl` (structured logs)

Console mode note:
- `python -m livekit_agent.agent console --record` also writes a LiveKit SDK session artifact directory under
  `console-recordings/` (includes `session_report.json` + audio recording metadata).

One-command local run (backend + audio console + saved artifacts):
```bash
./scripts/run_local_audio_console.sh
```

Agent behavior gotchas:
- **Backend-first vs OpenAI-first**:
  - Default (`AGENT_BACKEND_GUARDRAILS=true`): agent calls `get_case_status` on every user turn.
  - OpenAI-first (`AGENT_BACKEND_GUARDRAILS=false`): agent calls tools only when the model asks.

Local backend (in-memory DB) for quick reproductions:
```bash
USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

## Deterministic repro (fast, no LiveKit/Railway required)
When debugging logic (not networking), use tests:

```bash
# Agent unit/integration-ish tests (default pytest target):
python -m pytest -q

# Full repo tests (agent + api_server):
./scripts/test_all.sh

```

## When asking for help (keep it short)
Provide:
- `serverUrl` (non-secret) + token **payload** (redact signature)
- Browser + OS + VPN/corp network info
- LiveKit connection test result
- LiveKit SDK logs + WebRTC dump
- Railway log snippet (filtered) or agent log excerpt

## Failure modes / gotchas (high-signal)
- **Symptom:** agent sounds like it is "talking to itself" / constantly interrupts / responses get cancelled (can feel like "two agents")  
  **Likely cause:** barge-in/echo (most common: mobile speakerphone or laptop speakers causing the agent's audio to re-trigger the mic)  
  **Fix:** turn off speakerphone, use headphones/earpiece, lower volume, verify input/output devices (`python -m livekit_agent.agent console --list-devices`)
- **Symptom:** greeting plays, you speak, then silence (no follow-up reply)  
  **Likely cause:** Realtime server-side turn detection + `turn_detection.create_response=false` → the SDK may not call `on_user_turn_completed`, so no backend-first reply trigger occurs  
  **Fix:** enable `VOICE_DEBUG=1` and look for `VOICE_DEBUG user_input_transcribed` without a later `VOICE_DEBUG speech_created`; ensure the transcript-driven fallback is active in [`OpenAIRealtimeAgent._install_realtime_transcript_listener`](../../livekit_agent/openai_realtime_agent.py#L267) and that backend guidance is being injected via per-turn `instructions` (see [`OpenAIRealtimeAgent._handle_user_text_turn`](../../livekit_agent/openai_realtime_agent.py#L332))
- **Symptom:** Railway shows `/tools` 400 with `Invalid JSON payload`  
  **Likely cause:** a caller hit `/tools` with an empty or non-JSON body  
  **Fix:** ensure callers send a valid JSON body and include `X-TOOLS-TOKEN` (see `api_server/tools/router.py`)

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
- `docs/instructions/debug-livekit-agent-silence.md`
