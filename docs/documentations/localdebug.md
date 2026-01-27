# Local Debugging (Console Mode)

## Big picture
Local debugging is fastest when you can:
1) run the agent + backend locally, and
2) save durable artifacts (logs + tool traces + session reports) so you don't have to scroll terminal output.

This repo now supports a local “record everything” workflow via:
- `LOCAL_OBSERVABILITY_DIR` (writes JSONL logs + tool traces + session reports to disk)
- `python -m livekit_agent.agent console --record` (LiveKit SDK console recordings)
- `./scripts/run_local_audio_console.sh` (one-command: backend + audio console + artifacts)

Important: console mode still uses external STT/TTS providers (Deepgram/Cartesia) unless you swap them out.

## Quick start (recommended)
Run backend + agent locally, in audio mode, and save logs/artifacts to a per-run folder:

```bash
./scripts/run_local_audio_console.sh
```

Defaults this script sets (override at invocation time if needed):
- `AGENT_FAST_INTAKE=1` + `AGENT_GREETING="Hello, this is Sarah from AFS, how can I help?"`
- `GET_CASE_STATUS_FAST_EXTRACTOR=1` and Gemini features **off** (`GET_CASE_STATUS_GEMINI_*=0`) for speed/determinism

Enable Gemini (networked) for `get_case_status` if you want to test it:
```bash
GET_CASE_STATUS_GEMINI_CLASSIFICATION=1 \
GET_CASE_STATUS_GEMINI_EXTRACTION=1 \
GET_CASE_STATUS_GEMINI_CORRECTIONS=1 \
./scripts/run_local_audio_console.sh
```

Artifacts are written under:
- `local-observability/run-<timestamp>/`

You get:
- `agent.log.jsonl` (agent logs)
- `backend.log.jsonl` (backend logs)
- `backend.tools.jsonl` (one JSONL event per `/vapi/tools` request with tool names + result keys)
- `session-reports/*.json` (persisted session reports ingested at session end)
- `backend.stdout.log` (uvicorn stdout/stderr)

LiveKit console recordings (when `--record` is on) also go to:
- `console-recordings/session-*/session_report.json`

## Debug locally (agent) — options + tradeoffs
Debugging is fastest when you isolate the layer you care about. A good default progression is:
1) text-only (tests/evals) → 2) terminal voice → 3) real rooms/audio → 4) container.

### 1) Offline tests + offline evals (no LiveKit, no audio)
How:
```bash
python -m pytest -q
python -m livekit_agent.evals --list
python -m livekit_agent.evals --scenario preflight_no_sip_speak_first
```
Pros:
- Fastest iteration loop and easiest to debug with breakpoints.
- Deterministic and cheap (no WebRTC/mic/device issues).
Cons:
- Does not exercise WebRTC, mic permissions, or the STT/TTS pipeline.

### 2) Run the tools backend locally (then point the agent at it)
How:
```bash
# Backend (no Postgres required)
USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000

# Then run the agent with:
export BACKEND_TOOLS_URL="http://127.0.0.1:8000/vapi/tools"
```
Pros:
- Best way to debug the tool contract (exact payloads/responses) locally.
- Avoids waiting on Railway deploys.
Cons:
- Two processes to manage.
- In-memory mode differs from Postgres (state is lost on restart).

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
- Still depends on STT/TTS providers (Deepgram/Cartesia) unless you change config.
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
- STT/TTS still hit external APIs unless swapped/mocked.

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
- **Audio console mode works locally**: The agent starts in console mode, opens Deepgram STT + Cartesia TTS sockets, and receives transcripts.
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
curl -sS http://127.0.0.1:8000/vapi/tools \
  -H "Content-Type: application/json" \
  -d '{"message":{"type":"tool-calls","call":{"id":"debug-call","customer":{"number":"+13053179840"}},"customer":{"number":"+13053179840"},"toolCallList":[{"id":"tool-1","function":{"name":"get_case_status","arguments":"{\"last_user_message\":\"I have a flat tire.\"}"}}]}}' | jq .
```
Expected output:
- Returns a JSON tool result (no HTTP error).
- After the 2026-01-26 fixes, you should generally see a non-empty `immediate_message` when info is missing.

## Implication
If the agent appears “stuck” locally, it usually means one of:
- You disabled fast intake (`AGENT_FAST_INTAKE=0`) and preflight isn't complete yet (callback number / customer check gate).
- STT/TTS provider connectivity issues.
- Backend is returning `response_mode="tool_first"` with an empty `immediate_message` (silence).

The local artifacts in `LOCAL_OBSERVABILITY_DIR` make this easy to confirm without copy/paste.

## Services involved
- Agent: `python -m livekit_agent.agent console`
- Backend: `USE_IN_MEMORY_DB=1 python -m uvicorn api_server.server.fastapi_app:app --host 127.0.0.1 --port 8000`
