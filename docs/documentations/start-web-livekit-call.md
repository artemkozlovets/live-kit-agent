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
Use the LiveKit CLI (preferred for dev) or the Cloud dashboard.

**CLI (Cloud example):**
```bash
lk token create \
  --api-key <PROJECT_KEY> --api-secret <PROJECT_SECRET> \
  --join --room demo-room --identity demo-user \
  --valid-for 24h
```

Notes:
- `--room` is the room name (any string).
- `--identity` must be **unique per participant**.
- If you open a second tab, generate a **second token** with a different identity.

### 3) Join in LiveKit Meet
1. Open LiveKit Meet in the browser.
2. Choose the **Custom** tab.
3. Paste your **Server URL** and **Token**.
4. Click **Connect** and allow mic/camera permissions.

## Quick troubleshooting
- **Can’t connect?** Verify the `wss://` URL and token are from the same project.
- **Audio/video missing?** Check browser permissions for mic/camera.
- **Second participant fails?** Use a new token with a different `--identity`.

