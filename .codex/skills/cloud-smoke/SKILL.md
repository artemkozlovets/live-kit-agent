---
name: cloud-smoke
description: Run LiveKit Cloud end-to-end smoke tests (text/audio) against the deployed agent via lk, and debug failures using session reports.
metadata:
  short-description: Run LiveKit Cloud smoke tests
---

# LiveKit Cloud Smoke Tests

## Big picture
Use smoke tests like “unit tests for deployments”:
- unit tests prove local logic
- cloud smokes prove **deploy + LiveKit wiring + Realtime + backend session reports**

This repo’s canonical cloud smoke runner is:
- `./scripts/run_livekit_cloud_smoke.sh` (wrapper)
- `scripts/livekit_cloud_smoke.py` (runner; writes artifacts under `local-observability/`)

## Preconditions
- `lk` CLI points at the intended project + agent: `cat livekit.toml`
- Session report pipeline is configured for the deployed agent:
  - agent secret: `SESSION_REPORTS_URL`
  - optional auth: `SESSION_REPORTS_TOKEN`

## Quick run
```bash
# both (default)
./scripts/run_livekit_cloud_smoke.sh

# just text
./scripts/run_livekit_cloud_smoke.sh --scenario text

# just audio (transcription + reply)
./scripts/run_livekit_cloud_smoke.sh --scenario audio

# transfer prompt path (frustration + confirmation → tool call)
./scripts/run_livekit_cloud_smoke.sh --scenario transfer
```

## Recommended workflow (when shipping a feature)
1) Run local tests:
   - `python -m pytest -q`
   - `./scripts/test_all.sh` (before final handoff)
2) Deploy agent (when agent code changed):
   - `lk agent deploy`
3) Run cloud smoke(s) after deploy:
   - `./scripts/run_livekit_cloud_smoke.sh`

If the backend changed too, deploy it first (Railway), then run cloud smokes.

## If it fails (debug checklist)
1) Open `local-observability/run-*-livekit-cloud-smoke/result.json` for the failing room name + reason.
2) Fetch the session report for that room:
   - `./scripts/fetch_session_reports.py --url \"$SESSION_REPORTS_URL\" --room \"<room_name>\" --raw`
3) Tail LiveKit Cloud agent logs for the same room name:
   - `lk agent logs --log-type deploy`
4) If it’s an audio failure, inspect:
   - `local-observability/run-*-livekit-cloud-smoke/audio/lk_room_join.log`
