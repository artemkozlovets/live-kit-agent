# Vapi → LiveKit migration (Milestone 1)

This repo contains the Milestone 1 foundations for migrating the voice runtime from Vapi to LiveKit while keeping the backend tool contract (`POST /vapi/tools`) unchanged.

## What’s implemented
- Vapi-shaped tool-call payload builder: `livekit_agent/vapi_payload.py`
- Backend tools client (async) with typed errors: `livekit_agent/backend_tools_client.py`
- Tool schema loader from `squad/assistants/*.json` (+ local handoff tool schemas): `livekit_agent/tools.py`
- Deterministic flow controller (preflight callback gate + phase transitions + response_mode ordering): `livekit_agent/flow_controller.py`

## Run tests
```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Next step (Phase 4.1+)
Implement the actual LiveKit Agents runtime entrypoint (and optional integration tests) once we agree on the `livekit-agents[...]` dependency set and the provider choices (STT/LLM/TTS).

