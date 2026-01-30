# Local Debugging (Console Mode)

## Big picture
Local debugging is fastest when you can:
1) run the agent + backend locally, and
2) save durable artifacts (logs + tool traces + session reports) so you don't have to scroll terminal output.

This repo now supports a local “record everything” workflow via:
- `LOCAL_OBSERVABILITY_DIR` (writes JSONL logs + tool traces + session reports to disk)
- `python -m livekit_agent.agent console --record` (LiveKit SDK console recordings)
- `./scripts/run_local_audio_console.sh` (one-command: backend + audio console + artifacts)

Important: this repo is OpenAI Realtime-only. Ensure `OPENAI_API_KEY` is set.

## Quick start (recommended)
Run backend + agent locally, in audio mode, and save logs/artifacts to a per-run folder:

```bash
./scripts/run_local_audio_console.sh
```

Options:
- Run text-only console (no mic/speaker issues): `CONSOLE_MODE=text ./scripts/run_local_audio_console.sh`
- Capture the full console output (useful when the console “drops”): `CAPTURE_CONSOLE_LOG=1 ./scripts/run_local_audio_console.sh`

Defaults this script sets (override at invocation time if needed):
- `AGENT_BACKEND_GUARDRAILS=1` (agent calls `get_case_status` on every user turn)

Artifacts are written under:
- `local-observability/run-<timestamp>/`

You get:
- `agent.log.jsonl` (agent logs)
- `backend.log.jsonl` (backend logs)
- `backend.tools.jsonl` (one JSONL event per `/tools` request with tool names + result keys)
- `session-reports/*.json` (persisted session reports ingested at session end)
- `backend.stdout.log` (uvicorn stdout/stderr)
- `console.tty.log` (only when `CAPTURE_CONSOLE_LOG=1`; captures the interactive console UI output)

Note: `backend.tools.jsonl` is created lazily (it won’t exist until the first successful `POST /tools`).

LiveKit console recordings (when `--record` is on) also go to:
- `console-recordings/session-*/session_report.json`

### If backend logs/tools are missing (port already in use)
If your `<RUN_DIR>/backend.stdout.log` contains:
- `error while attempting to bind on address ('127.0.0.1', 8000): address already in use`

…then the script could not start its own backend (something else is already listening on that port).

What you’ll see:
- `<RUN_DIR>/backend.tools.jsonl` might not exist, even though the agent is successfully calling tools.
- Tool traces will be written wherever the *other* backend set `LOCAL_OBSERVABILITY_DIR` (often an older `local-observability/run-*` folder).

Fix:
```bash
# Find what is listening on port 8000 (macOS):
lsof -nP -iTCP:8000 -sTCP:LISTEN

# Either stop it, or run this script on a different port:
BACKEND_PORT=8001 ./scripts/run_local_audio_console.sh
```

## Codex terminal workflow (recommended)
When debugging locally, the “best” workflow is **two terminals**:

1) **Terminal A: run the local stack and leave it running**
```bash
./scripts/run_local_audio_console.sh
```

This script:
- starts the tools backend on `http://127.0.0.1:8000` by default (override with `BACKEND_PORT=...`)
- starts the agent in LiveKit **console** mode
- writes artifacts under `local-observability/run-<timestamp>/`

Source: [`scripts/run_local_audio_console.sh`](../../scripts/run_local_audio_console.sh#L4-L70)

2) **Terminal B: verify + inspect without scrolling**
```bash
# Backend is up?
curl -fsS http://127.0.0.1:8000/health

# Tail the latest local run logs (replace <RUN_DIR> with the path printed by the script):
tail -n 200 "<RUN_DIR>/agent.log.jsonl"
tail -n 200 "<RUN_DIR>/backend.stdout.log"
```

## Run in a background terminal (detached)
If you want the local console running continuously in the background (so logs keep writing even when you close this terminal), start it in a detached screen session:

```bash
screen -dmS local_console bash -lc 'set -a; source .env; set +a; ./scripts/run_local_audio_console.sh'
```

Useful commands:
- Attach to the running session: `screen -r local_console`
- Detach from the session: press `Ctrl+A` then `D`
- Stop it completely: `screen -S local_console -X quit`

Logs/artifacts still go to the per-run folder printed by the script:
`local-observability/run-<timestamp>/`

### If it “lags” after you say a phone number (OpenAI Realtime)
If the agent seems stuck after you provide a phone number, the fastest way to determine where it’s “stuck” is the agent log.

Check `<RUN_DIR>/agent.log.jsonl`:
- If you see `executing tool` for `validate_phone` / `check_customer` and then `tools execution completed`, the backend tool loop is working.
- If you see lots of:
  - `OpenAI Realtime API response done but not complete with status: cancelled`

…then the assistant’s responses are being interrupted/cancelled (commonly: barge-in/echo where speaker output re-triggers the mic).

Fixes that usually help:
- Use headphones (prevents speaker → mic feedback).
- Lower speaker volume.
- Verify the output device (`python -m livekit_agent.agent console --list-devices` then `--output-device ...`).

### If the console “drops” (process exits / terminal session dies)
Console mode is interactive (TTY). If it exits unexpectedly:
- Check `<RUN_DIR>/agent.log.jsonl` for a traceback or fatal error.
- If you ran with `CAPTURE_CONSOLE_LOG=1`, check `<RUN_DIR>/console.tty.log` for the last UI output.
- If the only logs are “starting agent session” and nothing else, it likely exited before receiving any input.

### If audio is flaky (stay in audio)
When debugging audio issues, keep the console in audio mode and isolate the layer:
- **TTS (speaking):** run the automated Realtime audio smoke test (no mic) to confirm the model is producing audible output.
- **Mic (listening):** verify macOS mic permission for your terminal and select the correct input/output devices (`--list-devices` / `--input-device` / `--output-device`).

### Automated OpenAI Realtime audio smoke (no mic)
This verifies the **OpenAI Realtime “speaking” path** without:
- microphone / device permissions
- LiveKit rooms / WebRTC
- the tools backend

How:
```bash
./scripts/run_openai_realtime_audio_smoke.sh \
  --turn "Please say: 'OpenAI realtime audio smoke test OK.'" \
  --modalities "text,audio"
```

Artifacts are saved under `local-observability/run-*-openai-realtime-audio-smoke/`:
- `assistant.wav` (agent audio output)
- `transcript.json` (user/assistant text + segment boundaries)
- `meta.json` (run config + audio stats)

If it fails with “No audio frames were captured”:
- ensure `OPENAI_API_KEY` is set
- ensure `--modalities` includes `audio`
- try setting `--voice` (or `OPENAI_REALTIME_VOICE`)

### Automated customer lookup smoke (no mic, hits your DB)
This verifies the “is this phone number in the database?” path by calling:
- `validate_phone`
- `check_customer`

It also optionally generates OpenAI Realtime audio output (`assistant.wav`) so you can confirm speech still works.

Example:
```bash
./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "305 555 0123" \
  --expect-found true
```

Artifacts are saved under `local-observability/run-*-openai-realtime-customer-lookup-smoke/`:
- `validate_phone.json`
- `check_customer.json`
- `result.json`
- `assistant.wav` (when `--with-audio true`, default)

If you only want the DB lookup (no OpenAI call), run:
```bash
./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "305 555 0123" \
  --with-audio false
```

### If OpenAI Realtime won’t start (missing plugin/key)
The default engine is `openai_realtime`, which requires:
- `OPENAI_API_KEY` set in your environment
- the LiveKit OpenAI plugin installed (`livekit-agents[openai]`)

If you see errors like “OpenAI Realtime plugin not installed”, install the extra:
```bash
.venv/bin/python -m pip install "livekit-agents[openai]"
```

Source: the plugin is imported lazily in [`livekit_agent/openai_realtime_session.py`](../../livekit_agent/openai_realtime_session.py#L8-L28).

### Pick the right mic/speaker (device selection)
```bash
# List devices (IDs + names)
python -m livekit_agent.agent console --list-devices

# Force an input/output device (use IDs or name substrings)
python -m livekit_agent.agent console --input-device 0 --output-device 1
```

## Debug locally (agent) — options + tradeoffs
Debugging is fastest when you isolate the layer you care about. A good default progression is:
1) tests → 2) terminal voice → 3) real rooms/audio → 4) container.

### 1) Tests (no LiveKit, no audio)
How:
```bash
python -m pytest -q
./scripts/test_all.sh
```
Pros:
- Fastest iteration loop and easiest to debug with breakpoints.
- Deterministic and cheap (no WebRTC/mic/device issues).
Cons:
- Does not exercise WebRTC, mic permissions, or realtime audio behavior.

### 2) Run the tools backend locally (then point the agent at it)
How:
```bash
# Backend (no Postgres required)
TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000

# Then run the agent with:
export BACKEND_TOOLS_URL="http://127.0.0.1:8000/tools"
export TOOLS_TOKEN="dev-secret"
```
Pros:
- Best way to debug the tool contract (exact payloads/responses) locally.
- Avoids waiting on Railway deploys.
Cons:
- Two processes to manage.
- In-memory mode differs from Postgres (state is lost on restart).

Use the Railway Postgres DB locally (when debugging customer lookup / DB issues):
```bash
# Runs the backend locally, but loads DATABASE_URL (and other vars) from Railway.
# Note: this does NOT print the variables; it just injects them into the process.
railway run --service "Call-agent" --environment development \
  .venv/bin/python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000
```

Notes:
- Your local agent still needs `TOOLS_TOKEN` to match the backend, and `OPENAI_API_KEY` if using OpenAI Realtime.
- If you want a DB shell without exporting secrets, use `railway connect` (Postgres → `psql`).

Local observability add-on (recommended):
```bash
export LOCAL_OBSERVABILITY_DIR="./local-observability/manual"
export SESSION_REPORTS_URL="http://127.0.0.1:8000/observability/session-report"
```

### 3) Agent `console` mode (terminal voice, local-only)
How:
```bash
python -m livekit_agent.agent console
```
Record audio + session report to `console-recordings/`:
```bash
python -m livekit_agent.agent console --record
```
Pros:
- Agent runs fully locally (great for breakpoints/logging).
- No LiveKit server required.
Cons:
- Still depends on OpenAI Realtime (network + OpenAI API key).
- Terminal audio can be finicky and is not identical to real rooms.

### 4) Agent `dev` mode against LiveKit Cloud (real rooms, local code)
How:
```bash
python -m livekit_agent.agent dev
```
Pros:
- Exercises real rooms + WebRTC while keeping the agent local for debugging.
- Closest “end-to-end” loop without deploying.
Cons:
- Requires correct LiveKit Cloud project URL/keys and working network/TURN.
- More moving parts; failures can be outside your code (VPN/corp firewall).

### 5) Agent `dev` mode against a local LiveKit server (fully local transport)
How:
```bash
livekit-server --dev

# In another terminal:
export LIVEKIT_URL="ws://localhost:7880"
export LIVEKIT_API_KEY="devkey"
export LIVEKIT_API_SECRET="secret"
python -m livekit_agent.agent dev
```
Pros:
- Fully local and reproducible for transport/room wiring issues.
- Great for debugging without any LiveKit Cloud dependencies.
Cons:
- You run/maintain the local server (ports, networking).
- OpenAI Realtime still hits external APIs (network required).

### 6) Deterministic audio publish via CLI (no mic/browser)
Use this when the agent “joins but is silent” and you want to remove mic/app variables.

How (Ogg Opus required):
```bash
lk room join <ROOM> --identity smoke_tester --publish /path/to/speech.ogg --auto-subscribe
```
Pros:
- Eliminates mic permissions, device selection, and frontend publishing bugs.
- Great for “does the agent hear audio and respond?” triage.
Cons:
- Not interactive; file format constraints (must be Ogg Opus).
- Still exercises the full realtime audio pipeline (more complexity than evals).

### 7) Docker Compose (production-ish packaging, local logs/metrics)
How:
```bash
docker compose up --build
```
Pros:
- Reproduces “runs in a container” issues (env, ports, dependencies).
- Easy access to worker endpoints/metrics (see README).
Cons:
- Slow iteration loop (rebuilds).
- Debugger/breakpoints require extra setup (ex: `debugpy` + port mapping).

### 8) Debugger attach vs logs/metrics (works with any run mode)
Debugger attach example (VS Code/PyCharm/etc.):
```bash
python -m debugpy --listen 5678 --wait-for-client -m livekit_agent.agent dev
```
Pros:
- Debugger is best for logic bugs; logs/metrics are best for realtime timing issues.
Cons:
- Breakpoints can disrupt realtime sessions; logs can be noisy.

## What we observed (2026-01-25)
- **Audio console mode works locally**: The agent starts in console mode and uses OpenAI Realtime.
- **Backend calls succeed**: `validate_phone`, `check_customer`, and `get_case_status` return `200 OK` from the local tools backend (`127.0.0.1:8000`).
- **“Lag” root cause**: `get_case_status` returns:
  - `response_mode: "tool_first"`
  - `immediate_message: null`
  - `then_action: "This is a new call. Start by collecting the customer's name."`
  This yields **no spoken output**, so the user hears silence even though the system is working.

## Fixes + improvements we added (2026-01-26)
To make local debugging less painful and reduce “stuck/silent” behavior:
- **Backend now returns speakable prompts** (non-empty `immediate_message`) when required fields are missing, so the agent doesn't go silent.
- **Persist key session fields** in local runs:
  - Persist normalized `phone_number` during `validate_phone` so the flow doesn't re-ask forever.
  - Deterministic 1-word name fallback (e.g., "John") so STT quirks don't stall intake.
- **Local observability artifacts**:
  - Set `LOCAL_OBSERVABILITY_DIR=...` to save `backend.log.jsonl`, `agent.log.jsonl`, `backend.tools.jsonl`, and `session-reports/*.json`.
  - Added `./scripts/run_local_audio_console.sh` to run everything with one command and auto-create a per-run artifacts folder.
- **Env sanity check**:
  - `GET /health/env` to confirm keys are loaded (without printing secrets).
  - Backend now auto-loads `.env` when running via uvicorn (so you don't have to `source .env` manually).

## Repro (backend-only, no audio/TTY needed)
```bash
curl -sS http://127.0.0.1:8000/tools \
  -H "Content-Type: application/json" \
  -H "X-TOOLS-TOKEN: dev-secret" \
  -d '{"call":{"id":"debug-call","customer":{"number":"+13055550123"}},"tool_calls":[{"id":"tool-1","name":"get_case_status","arguments":{"last_user_message":"I have a flat tire.","expected_field":null}}]}' | jq .
```
Expected output:
- Returns a JSON tool result (no HTTP error).
- After the 2026-01-26 fixes, you should generally see a non-empty `immediate_message` when info is missing.

## Implication
If the agent appears “stuck” locally, it usually means one of:
- Backend tools are unreachable (agent can't complete the loop).
- OpenAI Realtime responses are being interrupted/cancelled (common: speaker → mic feedback).
- Backend is returning `response_mode="tool_first"` with an empty `immediate_message` (silence).

The local artifacts in `LOCAL_OBSERVABILITY_DIR` make this easy to confirm without copy/paste.

## Services involved
- Agent: `python -m livekit_agent.agent console`
- Backend: `TOOLS_TOKEN=dev-secret USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
