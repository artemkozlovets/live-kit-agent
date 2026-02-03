# Deploy LiveKit Cloud Agent + Smoke Test

> **Last Updated**: 2026-02-02  
> **Audience**: Humans + Codex  
> **Status**: Draft

## TL;DR
- Deploy the agent: `lk agent deploy` (uses `livekit.toml` + `Dockerfile`).
- Verify it’s up: `lk agent status` + `lk agent logs --log-type deploy`.
- Gate the deploy: `./scripts/run_livekit_cloud_smoke.sh` (text + audio; asserts via session report).

## Big picture
This repo has **two deployed services**:
1) **LiveKit Cloud Agent** (this repo’s `livekit_agent/`), deployed via the LiveKit CLI (`lk`).  
2) **Tools backend** (FastAPI in `api_server/`), typically deployed to Railway.

The agent joins LiveKit rooms as a participant and calls the backend over HTTP (`POST /tools`).

## Preconditions (must be true)
- You’re authenticated to LiveKit Cloud: `lk cloud auth`
- `livekit.toml` points to the intended project + agent:
  - `cat livekit.toml`
  - `lk project list`
  - `lk agent status`
- The backend tools API is deployed and reachable (normally Railway), and the agent can call it:
  - Agent secret: `BACKEND_TOOLS_URL` ends with `/tools`
  - Agent + backend: `TOOLS_TOKEN` match (agent sends header `X-TOOLS-TOKEN`)
- For the default OpenAI Realtime path, the agent has `OPENAI_API_KEY` set.

Related: `docs/instructions/verify-railway-livekit-sync.md`

## Deploy (new version)
1) Sanity check you’re deploying to the right target:
```bash
cat livekit.toml
lk project list
lk agent status
lk agent secrets
```

2) Deploy:
```bash
lk agent deploy
```

Notes:
- `lk agent deploy` uploads the repo as a build context, builds `Dockerfile`, and rolls out a new version.
- Use `lk agent create` only when you need a brand-new agent registration / ID (it will generate `livekit.toml`).

3) Watch build + runtime logs:
```bash
lk agent logs --log-type build
lk agent logs --log-type deploy
lk agent status
```

Notes:
- `lk agent logs` is a **tail** command (stop with Ctrl+C). It doesn’t support `--lines`.

## Optional: reduce interruptions (recommended for PSTN)
If calls feel interrupt-y (especially on speakerphone / noisy environments), tune the Realtime turn detection and interruption thresholds via agent secrets.

See `docs/documentations/voice-interruptions.md` for root causes and how to confirm via session reports.

Recommended starting point:
```bash
lk agent update-secrets \
  --secrets "OPENAI_REALTIME_EAGERNESS=low" \
  --secrets "REALTIME_TRANSCRIPT_DEBOUNCE_S=0.6" \
  --secrets "REALTIME_TRANSCRIPT_POST_SILENCE_S=0.3" \
  --secrets "REALTIME_TRANSCRIPT_MAX_WAIT_S=8.0" \
  --secrets "LK_MIN_INTERRUPTION_DURATION_S=1.0"
```

Notes:
- Updating secrets restarts the agent.
- After changing these, rerun the smoke gate: `./scripts/run_livekit_cloud_smoke.sh`.

## Smoke test (no browser)
This repo’s recommended deploy gate is a **no-browser**, deterministic smoke test that:
- creates a room,
- dispatches the deployed agent,
- sends text and publishes a known-good Ogg Opus audio sample, then
- asserts on the backend **session report** artifact.

Run both scenarios (default):
```bash
./scripts/run_livekit_cloud_smoke.sh
```

Run a single scenario:
```bash
./scripts/run_livekit_cloud_smoke.sh --scenario text
./scripts/run_livekit_cloud_smoke.sh --scenario audio
```

Artifacts are saved under:
- `local-observability/run-*-livekit-cloud-smoke/`

Related: `docs/instructions/openai-realtime-rollout.md`

## Common failures (what to check first)
- **Smoke script says `.venv/bin/python` is missing** → create venv and install deps:
  - `python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`
- **Timeout waiting for session report** → agent may not be publishing reports or backend isn’t storing them:
  - Check agent secrets: `SESSION_REPORTS_URL` (and optional `SESSION_REPORTS_TOKEN`)
  - Check backend has `SESSION_REPORTS_TOKEN` if auth is enabled
  - See: `docs/documentations/debug.md` (Programmatic observability)
- **401/403 when fetching report** → set `SESSION_REPORTS_TOKEN` in your shell (or pass `--reports-token`).
- **No assistant reply after user message / transcript** → check:
  - `lk agent logs --log-type deploy` for `AgentSession error`
  - Railway logs for `/tools` returning `401/5xx` (tool loop blocked)

## Rollback
- Paid plans support instant rollback: `lk agent rollback`
- Otherwise: revert code to a known-good commit and redeploy with `lk agent deploy`.
