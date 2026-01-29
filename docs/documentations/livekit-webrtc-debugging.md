# LiveKit WebRTC Debugging (No Backend)

> **Last Updated**: 2026-01-25  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- First isolate **server URL + token + network** vs **your app code** by joining the same room in LiveKit Meet.
- Debug “can’t connect” with LiveKit’s **connection test** (WebSocket / ICE / TURN).
- Debug “connects but media is broken” with **SDK logs** + **browser WebRTC dumps**.
- For “no backend” token generation, use LiveKit Cloud’s **sandbox token server** or `lk token create`.

## What “no backend” means
You still need a LiveKit server (LiveKit Cloud project or a self-hosted LiveKit server), but you *don’t* need:
- your own token endpoint
- your tools backend (Railway / `api_server/`)

This doc is focused on debugging the WebRTC layer (browser/app connectivity + media).

## 0) Always isolate: LiveKit vs your app
1. Get your LiveKit **Project URL** (`wss://...`) from LiveKit Cloud project settings (or use `ws://localhost:7880` for local dev).
2. Generate a **join token** (see below).
3. Join via LiveKit Meet:
   - Recommended: use a **full Meet link**: `https://meet.livekit.io/custom?liveKitUrl=<WS_URL>&token=<JWT>`
   - Fallback: open LiveKit Meet → **Custom** tab → paste `serverUrl` + token.

Interpretation:
- **Meet fails** with the same URL/token → fix URL/token/network first (not your app).
- **Meet works** but your app fails → it’s almost always client code/config (options, device permissions, event handling).

## 1) Get a token without writing a backend

### Option A: LiveKit Cloud sandbox token server (recommended for dev)
LiveKit Cloud can host a dev-only token server (“sandbox token generation”). It’s insecure by design (anyone who knows the sandbox ID can request broad tokens), so do not use it for production.

Docs: `https://docs.livekit.io/frontends/authentication/tokens/sandbox-token-server/`

Minimal JS example:
```ts
import { Room, TokenSource } from "livekit-client";

const tokenSource = TokenSource.sandboxTokenServer({ sandboxId: "<your-sandbox-id>" });
const { serverUrl, participantToken } = await tokenSource.fetch({ roomName: "debug-room" });

const room = new Room();
await room.connect(serverUrl, participantToken);
```

### Option B: `lk token create` (CLI)
The LiveKit CLI can mint a join token from your API key/secret (no server call required).

Docs: `https://docs.livekit.io/intro/basics/cli/start/#generate-access-token`

```bash
lk token create \
  --api-key <PROJECT_KEY> --api-secret <PROJECT_SECRET> \
  --join --room debug-room --identity debug-user \
  --valid-for 1h
```

Or (recommended): print a **full Meet link** you can click/share:
```bash
ROOM="debug-room"
IDENTITY="debug-user"

OUT="$(lk token create --join --room "$ROOM" --identity "$IDENTITY" --valid-for 1h)"
LIVEKIT_URL="$(printf "%s\n" "$OUT" | rg '^Project URL:' | awk '{print $3}')"
TOKEN="$(printf "%s\n" "$OUT" | rg '^Access token:' | awk '{print $3}')"

echo "https://meet.livekit.io/custom?liveKitUrl=${LIVEKIT_URL}&token=${TOKEN}"
```

## 2) Diagnose “can’t connect” (network / TURN / firewall)

### Use LiveKit connection test
Run: `https://livekit.io/connection-test`

Use the exact same `serverUrl` + token as your app. This quickly tells you whether the failure is:
- signaling (WebSocket)
- ICE candidate gathering
- TURN connectivity (common on VPN/corporate networks)
- DTLS/SRTP negotiation

### Force relay-only to confirm UDP/firewall issues (JS)
If a user is on a restrictive network, forcing TURN relay can confirm the root cause.

LiveKit JS `Room.connect` accepts `RoomConnectOptions` with `rtcConfig`:
Docs: `https://docs.livekit.io/reference/client-sdk-js/interfaces/RoomConnectOptions.html`

```ts
await room.connect(wsUrl, token, {
  rtcConfig: { iceTransportPolicy: "relay" },
});
```

Interpretation:
- **Default fails, relay-only works** → UDP is likely blocked; rely on TURN/TLS and set expectations for higher latency.
- **Relay-only fails too** → TURN may be blocked/misconfigured, or the token/server URL is wrong.

## 3) Diagnose “connects but media is broken” (client / devices / browser)

### Turn on LiveKit JS SDK logs
Docs: `https://docs.livekit.io/reference/client-sdk-js/functions/setLogLevel.html`

```ts
import { setLogLevel } from "livekit-client";

setLogLevel("debug"); // use "trace" if needed
```

Also log browser-level errors:
- mic/camera permissions (denied, no device, device busy)
- autoplay restrictions (audio won’t play until user gesture)
- “secure context” issues (camera/mic require HTTPS on most browsers)

### Capture a WebRTC dump
- Chrome: `chrome://webrtc-internals` → “Create dump”
- Firefox: `about:webrtc`

These dumps show ICE candidates, selected candidate pair, TURN usage, packet loss, and audio/video RTP stats.

## 4) What to collect when asking for help
Keep the signal high so debugging is fast:
- Browser + OS + “on VPN/corp network?”
- `serverUrl` (not secret) and whether it’s LiveKit Cloud vs self-hosted
- Token **payload** (decoded locally; redact signature/secret material)
- `https://livekit.io/connection-test` results (screenshot or paste)
- LiveKit SDK logs with `setLogLevel("debug")`
- A WebRTC dump (`chrome://webrtc-internals` or `about:webrtc`)

## Related repo docs
- `docs/documentations/livekit-agent.md` (agent runtime + tools contract; not needed for pure WebRTC debugging)
- `docs/instructions/debug-livekit-agent-silence.md` (end-to-end agent silence runbook)

## Appendix: CLI media publish smoke test (no browser code)
Use `lk room join --publish` to simulate a publisher. For **audio**, the file must be **Ogg Opus**.

```bash
# Join (and publish) using an Ogg Opus sample (no ffmpeg required)
curl -L -o /tmp/speech.opus \
  https://upload.wikimedia.org/wikipedia/commons/9/96/Speech_12dB_opus_7kbps.opus
cp /tmp/speech.opus /tmp/speech.ogg
file /tmp/speech.ogg  # expect: "Ogg data, Opus audio ..."

lk room join <ROOM> \
  --identity smoke_tester \
  --publish /tmp/speech.ogg \
  --auto-subscribe
```

If you publish Ogg Vorbis instead of Opus, `lk` may fail with Ogg/Opus framing errors.
