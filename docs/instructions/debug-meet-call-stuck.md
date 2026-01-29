# Debug LiveKit Meet Call “Stuck” (Codex Context)

> **Last Updated**: 2026-01-29  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** debug a `meet.livekit.io/custom?...` call that appears stuck (example: “hangs after asking for phone number”).
- **Entry points:** agent engine selection + logging in [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1047), tools client auth in [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py#L67), backend auth in [`api_server/tools/router.py`](../../api_server/tools/router.py#L21).
- **Where to change:** LiveKit agent secrets (`AGENT_ENGINE`, `BACKEND_TOOLS_URL`, `TOOLS_TOKEN`, provider keys) and Railway backend vars (`TOOLS_TOKEN`).
- **Where tools run:** wherever `BACKEND_TOOLS_URL` points (normally **Railway** for Meet calls; `http://127.0.0.1:8000/tools` for local debug).
- **How to verify (fast):**
  - Unit tests: `./scripts/test_all.sh`
  - Backend auth: `curl -X POST https://<railway-domain>/tools` → `401` without header, `200` with header + valid body
  - End-to-end: `lk dispatch create` + `lk room join --publish /tmp/speech.ogg` + check Railway `/tools` logs for `200`

## Big picture
LiveKit Meet is just a frontend that **joins a LiveKit room**. The “asks for phone number” and any subsequent “stuck” behavior is driven by:

`LiveKit Meet (browser)` → `LiveKit Cloud room` → `LiveKit Cloud agent (this repo: livekit_agent/)` → `Tools backend (Railway: api_server/)`

So your debugging loop is always:
1) **Confirm the agent session is healthy** (`lk agent logs`), and
2) **Confirm the agent can talk to the tools backend** (`railway logs` for `POST /tools` + `200`).

## Key files
- [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1047) — chooses `AGENT_ENGINE` and logs engine + backend URL.
- [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py#L67) — sends `POST /tools` with `X-TOOLS-TOKEN` header.
- [`api_server/server/fastapi_app.py`](../../api_server/server/fastapi_app.py#L1) — mounts `api_server.tools.router` (v2 `/tools`).
- [`api_server/tools/router.py`](../../api_server/tools/router.py#L21) — enforces `TOOLS_TOKEN` and validates v2 request shape.

## Flow (happy path)
1. User joins a room in Meet (or via `lk room join ...`).
2. LiveKit Cloud dispatches your agent into that room.
3. Agent picks an engine:
   - `AGENT_ENGINE=openai_realtime` (default) or
   - `AGENT_ENGINE=legacy` (Deepgram STT + Cartesia TTS). See [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1052).
4. Agent POSTs tool calls to `BACKEND_TOOLS_URL` and includes `X-TOOLS-TOKEN`. See [`BackendToolsClient.call_tool`](../../livekit_agent/backend_tools_client.py#L74).
5. Backend returns `{"results":[...]}` and the agent continues the flow.

## Contracts / invariants (don’t break these)
- **Backend endpoint is v2 `POST /tools`** (no `POST /vapi/tools`): see [`docs/documentations/api-server.md`](../documentations/api-server.md#L7) and backend router wiring [`api_server/server/fastapi_app.py`](../../api_server/server/fastapi_app.py#L103).
- **Auth is mandatory:** tools client sends `X-TOOLS-TOKEN` and backend validates it. See [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py#L98) and [`api_server/tools/router.py`](../../api_server/tools/router.py#L21).
- **Without `TOOLS_TOKEN`, the agent can’t call tools:** the client raises early. See [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py#L98).
- **Legacy engine uses an optional “tool LLM” (Gemini) for `then_action` parsing:** failures should fall back, but repeated timeouts can still degrade UX. See [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L890).

## Configuration (high-signal env vars)

### LiveKit Cloud agent secrets
- `AGENT_ENGINE` — `openai_realtime` (default) or `legacy` (see [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1053)).
- `BACKEND_TOOLS_URL` — must end with `/tools` (see [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1052)).
- `TOOLS_TOKEN` — shared secret for `X-TOOLS-TOKEN` (see [`BackendToolsClient.call_tool`](../../livekit_agent/backend_tools_client.py#L98)).
- `OPENAI_API_KEY` — required when `AGENT_ENGINE=openai_realtime` (see [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1142)).
- `GOOGLE_API_KEY` + `GOOGLE_LLM_*` — legacy-only “tool LLM” settings (see [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L1056) and [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L916)).

### Railway backend variables
- `TOOLS_TOKEN` — must match the agent’s `TOOLS_TOKEN` (see [`api_server/tools/router.py`](../../api_server/tools/router.py#L21)).
- `PORT` — provided by Railway (see `Dockerfile.backend`).

## Ops cheat sheet (Railway + `lk`)

### Find the Railway public domain
```bash
railway variables --service "Call-agent" --environment development --kv | rg RAILWAY_PUBLIC_DOMAIN
```

### Sync `TOOLS_TOKEN` (Railway + LiveKit agent)
```bash
railway variables --service "Call-agent" --environment development --set "TOOLS_TOKEN=<secret>"
lk agent update-secrets --secrets "TOOLS_TOKEN=<secret>"
```

### Ensure the agent points at v2 `/tools`
```bash
lk agent update-secrets --secrets "BACKEND_TOOLS_URL=https://<railway-domain>/tools"
```

### Prefer OpenAI Realtime (OpenAI-first flow)
If you want the conversation + extraction to live on the OpenAI side (less backend-driven slot-filling):
```bash
lk agent update-secrets --secrets "AGENT_ENGINE=openai_realtime"
lk agent update-secrets --secrets "OPENAI_API_KEY=<secret>"
lk agent update-secrets --secrets "AGENT_BACKEND_GUARDRAILS=false"
```

### Deploy
```bash
railway up --service "Call-agent" --environment development --detach
lk agent deploy
```

## Verification

### Happy path (tests)
```bash
./scripts/test_all.sh
```

### Happy path (backend health)
```bash
curl -sS "https://<railway-domain>/health"
```

### Edge case (auth)
Expect `401` when `X-TOOLS-TOKEN` is missing/invalid:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://<railway-domain>/tools"
```

### Failure case (legacy endpoint)
Expect `404` for removed legacy routes:
```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://<railway-domain>/vapi/tools"
```

### End-to-end smoke test (no browser)
1) Dispatch a fresh room:
```bash
AGENT_ID="$(python -c 'import tomllib; print(tomllib.load(open(\"livekit.toml\",\"rb\"))[\"agent\"][\"id\"])')"
lk dispatch create --new-room --agent-name "$AGENT_ID"
```
2) Generate a **full Meet link** for that room (recommended):
```bash
ROOM="<paste room name from dispatch output>"
IDENTITY="demo-user"

OUT="$(lk token create --join --room "$ROOM" --identity "$IDENTITY" --valid-for 1h)"
LIVEKIT_URL="$(printf "%s\n" "$OUT" | rg '^Project URL:' | awk '{print $3}')"
TOKEN="$(printf "%s\n" "$OUT" | rg '^Access token:' | awk '{print $3}')"

echo "https://meet.livekit.io/custom?liveKitUrl=${LIVEKIT_URL}&token=${TOKEN}"
```
3) Publish known-good audio and stay connected long enough to observe logs:
```bash
curl -L -o /tmp/speech.opus https://upload.wikimedia.org/wikipedia/commons/9/96/Speech_12dB_opus_7kbps.opus
cp /tmp/speech.opus /tmp/speech.ogg
lk room join <ROOM> --identity smoke_tester --publish /tmp/speech.ogg --auto-subscribe
```
4) In another terminal, confirm backend traffic:
```bash
railway logs --service "Call-agent" --environment development --lines 200 --filter "/tools"
```

## Failure modes / gotchas (symptom → likely cause → fix)
- **Stuck after phone number prompt** → agent is waiting on tool flow (preflight / `then_action` parsing / backend call) → check `lk agent logs` for tool/backends errors and Railway for `/tools` `200` vs `401/5xx`.
- **OpenAI-first says “checking the database” forever** → the model is likely *not actually calling tools* → confirm Railway has *no* matching `POST /tools` requests during the call, then redeploy the agent (older versions could hallucinate tool usage). Newer agent builds auto-trigger `validate_phone` + `check_customer` prefetch when a phone number is detected.
- **Railway `/tools` shows `401 Unauthorized`** → `TOOLS_TOKEN` missing/mismatched → set the same `TOOLS_TOKEN` in both places:
  - Railway: `railway variables --service "Call-agent" --environment development --set "TOOLS_TOKEN=<secret>"`
  - LiveKit: `lk agent update-secrets --secrets "TOOLS_TOKEN=<secret>"`
- **Railway shows `404` on `/vapi/tools`** → old `BACKEND_TOOLS_URL` still points at legacy path → set `BACKEND_TOOLS_URL=https://<railway-domain>/tools` and redeploy agent.
- **Agent logs show Gemini 504 / `DEADLINE_EXCEEDED`** (legacy tool LLM) → transient Gemini outage/slow response → consider disabling the tool-LLM (remove `GOOGLE_API_KEY`) or switching to `AGENT_ENGINE=openai_realtime` with `OPENAI_API_KEY`.
- **Call feels rigid / one-by-one prompts** → you’re likely running backend-first guardrails → set `AGENT_BACKEND_GUARDRAILS=false` (OpenAI-first) and redeploy the agent.
- **Agent logs show “closing agent session due to participant disconnect”** → the only user participant left the room (common if you use `--exit-after-publish`) → keep the publishing participant connected while debugging.
- **Railway logs are hard to correlate** → use JSON logs with timestamps:
  - `railway logs --lines 200 --filter "/tools" --json`
- **Railway variables output is hard to parse** → prefer KV output when checking whether a variable is set:
  - `railway variables --service "Call-agent" --environment development --kv`

## Related docs
- [`docs/documentations/start-web-livekit-call.md`](../documentations/start-web-livekit-call.md)
- [`docs/documentations/livekit-agent.md`](../documentations/livekit-agent.md)
- [`docs/documentations/api-server.md`](../documentations/api-server.md)
- [`docs/instructions/verify-railway-livekit-sync.md`](verify-railway-livekit-sync.md)
- [`docs/instructions/debug-livekit-agent-silence.md`](debug-livekit-agent-silence.md)
- [`docs/instructions/pull-railway-logs.md`](pull-railway-logs.md)
