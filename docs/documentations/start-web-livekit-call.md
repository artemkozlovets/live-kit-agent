# Start Web LiveKit Call (Meet)

> **Last Updated**: 2026-01-25  
> **Audience**: Codex + humans  
> **Status**: Draft

## Big picture
To start a web call in **LiveKit Meet**, you need two things:
1) Your **LiveKit server URL** (usually a `wss://...` Project URL in LiveKit Cloud), and  
2) A **participant access token** for a specific room + identity.

With those, you can join a room from the browser and start a realtime audio/video call.

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
