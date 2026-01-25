# Verify Railway ↔ LiveKit Sync

Last updated: 2026-01-24

## Big picture
This repo runs as **two deployed services**:
- **LiveKit Cloud Agent** (managed by `lk`): runs the voice worker.
- **Railway backend** (managed by `railway`): serves the tools API the agent calls (`POST /vapi/tools`), plus a health check (`GET /health`).

When we say “Railway and LiveKit are in sync”, we usually mean:
1) Railway is reachable + healthy,  
2) `lk` is pointing at the intended LiveKit Cloud project/agent, and  
3) the LiveKit agent has `BACKEND_TOOLS_URL` set (and is actually reaching Railway in logs).

## 1) Verify Railway CLI is connected
```bash
railway whoami
railway status
```

If `railway status` complains about no linked project, run:
```bash
railway link
```

## 2) Verify Railway backend health
The backend health check path is `/health` (see `railway.json`).

Get the public domain **without printing all variables** (some variables are secrets):
```bash
RAILWAY_DOMAIN="$(
  railway variables --service "Call-agent" --environment development --json \
    | python -c 'import json,sys; print(json.load(sys.stdin)["RAILWAY_PUBLIC_DOMAIN"])'
)"

curl -sS "https://${RAILWAY_DOMAIN}/health"
```

Expected: `{"status":"healthy"}` (HTTP 200).

## 3) Verify `lk` is pointed at the intended LiveKit Cloud project
`livekit.toml` is the local “pointer” to the target project/agent:
```bash
cat livekit.toml
lk project list
```

Make sure your default `lk` project URL matches the `livekit.toml` subdomain (example: `wss://<subdomain>.livekit.cloud`).

## 4) Verify the LiveKit agent is running + has backend config
```bash
lk agent status
lk agent secrets
```

You should see `BACKEND_TOOLS_URL` listed in `lk agent secrets`.

Note: the CLI does not print secret *values*; it only lists secret names.

## 5) Verify end-to-end: agent is actually hitting Railway
Trigger any real run (dispatch a room / place a test call), then check:

Railway logs (small, filter first):
```bash
railway logs --service "Call-agent" --environment development --lines 200 --filter "/vapi/tools"
railway logs --service "Call-agent" --environment development --lines 200 --filter "@level:error"
```

LiveKit agent logs (streams; press Ctrl+C to stop):
```bash
lk agent logs --log-type deploy
```

## 6) Optional: compare deployed “versions”
Local git state:
```bash
git rev-parse --abbrev-ref HEAD
git rev-parse --short HEAD
```

Railway deployment metadata (shows repo/branch/commit for the most recent deployment):
```bash
railway deployment list --service "Call-agent" --environment development --limit 1 --json \
  | python -c 'import json,sys; meta=json.load(sys.stdin)[0]["meta"]; print("repo:", meta.get("repo")); print("branch:", meta.get("branch")); print("commit:", meta.get("commitHash"))'
```

LiveKit agent versions:
```bash
lk agent versions
```
