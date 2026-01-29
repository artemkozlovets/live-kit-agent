# Start Web LiveKit Call (Meet)

> **Last Updated**: 2026-01-29  
> **Audience**: Codex + humans  
> **Status**: Draft

## Big picture
To start a web call in **LiveKit Meet**, you need two things:
1) Your **LiveKit server URL** (usually a `wss://...` Project URL in LiveKit Cloud), and  
2) A **participant access token** for a specific room + identity.

With those, you can join a room from the browser and start a realtime audio/video call.

If you want a “remote call” that includes **this repo’s deployed LiveKit agent**, you also need to
**dispatch the agent into the room** (see below).

## Steps (LiveKit Meet + token)

### 1) Get your LiveKit server URL
- **LiveKit Cloud**: copy your **Project URL** from Project Settings (starts with `wss://`).
- **Local dev**: use `ws://localhost:7880` (if you’re running LiveKit locally).

### 2) Generate a participant token
Pick one:

**Option A (dev): LiveKit Cloud sandbox token server**
- Docs: `https://docs.livekit.io/frontends/authentication/tokens/sandbox-token-server/`
- Useful when you don’t want to run your own token backend.

**Option B (dev): LiveKit CLI**

```bash
lk token create \
  --join --room demo-room --identity demo-user \
  --valid-for 24h
```

Notes:
- `--room` is the room name (any string).
- `--identity` must be **unique per participant**.
- If you open a second tab, generate a **second token** with a different identity.
- If you don’t have `LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` configured, pass `--api-key`/`--api-secret` explicitly.

### 3) Join in LiveKit Meet
Recommended: generate a **full Meet link** (skips the pre-join UI):
```bash
ROOM="demo-room"
IDENTITY="demo-user"

OUT="$(lk token create --join --room "$ROOM" --identity "$IDENTITY" --valid-for 1h)"
LIVEKIT_URL="$(printf "%s\n" "$OUT" | rg '^Project URL:' | awk '{print $3}')"
TOKEN="$(printf "%s\n" "$OUT" | rg '^Access token:' | awk '{print $3}')"

echo "https://meet.livekit.io/custom?liveKitUrl=${LIVEKIT_URL}&token=${TOKEN}"
```

Fallback (manual UI):
1. Open LiveKit Meet
2. Choose the **Custom** tab
3. Paste `serverUrl` + token
4. Click **Connect** and allow mic/camera permissions

Notes:
- URL-encode the token if your browser mangles it (rare).
- This is convenient for dev; don’t share links with long-lived tokens.

## Quick troubleshooting
- **Can’t connect?** Verify the `wss://` URL and token are from the same project.
- **Audio/video missing?** Check browser permissions for mic/camera.
- **Second participant fails?** Use a new token with a different `--identity`.

## Start a remote call with this repo’s deployed agent (LiveKit Cloud)

### Big picture
LiveKit Meet is just a frontend that joins a LiveKit room. This repo’s **agent** is a separate
participant that must be **dispatched** into that room.

### 0) Prereqs
- You’re authenticated to the right LiveKit Cloud account: `lk cloud auth`
- This repo points at the right project/agent: `cat livekit.toml`
- The agent is deployed and running: `lk agent status`

### 1) Create a room + dispatch the agent
```bash
AGENT_ID="$(
  python -c 'import tomllib; print(tomllib.load(open("livekit.toml","rb"))["agent"]["id"])'
)"

lk dispatch create --new-room --agent-name "$AGENT_ID"
```

If `tomllib` isn’t available (older Python), set `AGENT_ID` by copying it from `cat livekit.toml`.

Copy the new room name from the command output.

### 2) Join that room in LiveKit Meet
```bash
ROOM="<paste room name>"
IDENTITY="web-user-1"

OUT="$(lk token create --join --room "$ROOM" --identity "$IDENTITY" --valid-for 1h)"
LIVEKIT_URL="$(printf "%s\n" "$OUT" | rg '^Project URL:' | awk '{print $3}')"
TOKEN="$(printf "%s\n" "$OUT" | rg '^Access token:' | awk '{print $3}')"

echo "https://meet.livekit.io/custom?liveKitUrl=${LIVEKIT_URL}&token=${TOKEN}"
```

Open the printed link and allow mic permissions.

### 3) Quick checks (if the agent doesn’t show up)
```bash
lk room participants list "$ROOM"
lk agent logs --log-type deploy
```
