# Debug LiveKit Cloud Agent Silence (Codex Context)

> **Last Updated**: 2026-01-28  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** figure out why the LiveKit Cloud agent joins but “never responds”.
- **Entry points:** `lk agent logs`, `railway logs`, and the agent boot path in [`livekit_agent/agent.py`](../../livekit_agent/agent.py).
- **Where to change:**
  - Backend tools HTTP contract + errors: [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py#L69)
  - Backend `/tools` handler: [`api_server/tools/router.py`](../../api_server/tools/router.py)
- **How to verify:** dispatch a room + publish a known-good Ogg Opus sample via CLI (below), then confirm:
  - `lk agent logs` shows no `AgentSession error`
  - Railway logs show `POST /tools` `200`
  - `lk room join --auto-subscribe` sees the agent publish an audio track

## Big picture
A “silent” agent is almost always one of:
1. **No user audio reaches the agent** (you’re connected but not publishing mic audio / wrong codec / permissions).
2. **OpenAI Realtime session failed to start** (missing/invalid `OPENAI_API_KEY`, missing plugin, invalid config).
3. **The tools backend is unreachable or erroring** (agent can hear you but can’t complete the tool loop).
4. **The session is being closed** (participant disconnect, job ended, etc.).

This runbook prioritizes fast isolation via `lk` + `railway`.

## Preconditions (this repo)
- `livekit.toml` points `lk` at the intended project + agent: [`livekit.toml`](../../livekit.toml#L1)
- LiveKit Cloud agent requires:
  - `OPENAI_API_KEY` set
  - Backend tools URL from `BACKEND_TOOLS_URL`: [`livekit_agent/agent.py`](../../livekit_agent/agent.py)
- Railway runs the tools API (`POST /tools`): [`api_server/tools/router.py`](../../api_server/tools/router.py)

## 1) Sanity check CLI + pointers
```bash
# LiveKit target (from livekit.toml)
cat livekit.toml

# LiveKit Cloud agent is up
lk agent status
lk agent secrets

# Railway is linked + reachable
railway whoami
railway status
```

Success signals:
- `lk agent status` shows **Running**
- `lk agent secrets` includes `BACKEND_TOOLS_URL`, `TOOLS_TOKEN`, and (for default engine) `OPENAI_API_KEY` (names only; values hidden)
- `railway status` shows the expected Project/Env/Service

## 2) Reproduce with a CLI-only smoke test (Ogg Opus)
This isolates your frontend app + mic permissions from the equation.

### 2.1 Create a fresh room + dispatch the agent
```bash
# Pull the agent id from livekit.toml (source of truth for `lk` in this repo).
AGENT_ID="$(
  python -c 'import tomllib; print(tomllib.load(open("livekit.toml","rb"))["agent"]["id"])'
)"

lk dispatch create --new-room --agent-name "$AGENT_ID"
```

Copy the `room:"..."` from the output as `<ROOM>`.

If `python`/`tomllib` isn’t available, just copy the agent id from `lk agent status` or `cat livekit.toml` and pass it to `--agent-name`.

### 2.2 Publish known-good audio (Ogg Opus) + subscribe to the agent
```bash
# Download a tiny Opus sample and publish it (no ffmpeg required)
curl -L -o /tmp/speech.opus \
  https://upload.wikimedia.org/wikipedia/commons/9/96/Speech_12dB_opus_7kbps.opus
cp /tmp/speech.opus /tmp/speech.ogg
file /tmp/speech.ogg  # expect: "Ogg data, Opus audio ..."

# Join room, publish audio, and subscribe to remote tracks (including agent TTS)
lk room join <ROOM> \
  --identity smoke_tester \
  --publish /tmp/speech.ogg \
  --auto-subscribe
```

Success signals:
- In the `lk room join` output, you see `track subscribed ... participant agent-... kind audio`
- In Railway logs (next section), you see `POST /tools` → `200 OK`

Notes:
- If you use `--exit-after-publish`, you will disconnect immediately and the agent may close due to participant disconnect (expected in logs).
- `lk room join` is for verification; it’s not a great “listen to the audio” experience. Use Meet for real listening.

## 3) LiveKit Cloud logs: find the failure signature
Tail logs while reproducing:
```bash
lk agent logs --log-type deploy
```

High-signal patterns:

### A) OpenAI Realtime startup failure (common “silent” root cause)
Symptom in `lk agent logs`:
- `AgentSession error` early in session start (often before any `/tools` traffic).

Likely causes:
- Missing/invalid `OPENAI_API_KEY` (auth failure).
- OpenAI plugin missing from the deployed environment (install `livekit-agents[openai]`).
- Invalid `OPENAI_REALTIME_VOICE` (if set).

### B) Session closes due to participant disconnect
Symptom in `lk agent logs`:
- `closing agent session due to participant disconnect ...`

Interpretation:
- For CLI tests, keep the publishing participant connected long enough to observe agent output.

### C) Backend tools failures
Symptom in `lk agent logs`:
- “backend tools request failed/timed out” style warnings (from the backend client).

Backend client code:
- [`BackendToolsClient.call_tool`](../../livekit_agent/backend_tools_client.py#L69)

## 4) Railway logs: confirm tools traffic + backend errors
```bash
railway logs --service "Call-agent" --environment development --lines 200 --filter "/tools"
railway logs --service "Call-agent" --environment development --lines 200 --filter "@level:error"
```

High-signal patterns:

### A) `/tools` returns 401 Unauthorized
If Railway logs show:
- `401 Unauthorized`

Interpretation:
- The caller is missing `X-TOOLS-TOKEN` or it doesn't match the backend `TOOLS_TOKEN`.
- Check `lk agent secrets` (agent) and Railway env (backend) are set consistently.

### B) `/tools` returns 400 Invalid JSON payload
Interpretation:
- Something is calling `POST /tools` with an empty or non-JSON body.
- Check callers / health checks / any proxy that might be hitting the wrong path.

### C) `/tools` returns 500 for real tool errors
Interpretation:
- The backend threw inside dispatch.
- Narrow by time window and inspect stack traces in Railway logs.

## 5) Security follow-up (don’t skip)
Some upstream exceptions can include request headers in their message. The agent adds basic redaction:
- [`_redact_secrets`](../../livekit_agent/agent.py)

If you ever saw an API key/token in logs, rotate that credential.

## Related docs
- `docs/instructions/verify-railway-livekit-sync.md`
- `docs/instructions/pull-railway-logs.md`
- `docs/documentations/livekit-agent.md`
- `docs/documentations/livekit-webrtc-debugging.md`
