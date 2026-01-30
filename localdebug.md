# Local Debugging Notes

## Big picture
The fastest way to debug this repo locally is:
1) run the **tools backend** + the **LiveKit agent console (audio)** on your machine, and
2) save **durable artifacts** (agent logs, backend logs, `/tools` traces, session reports) to disk per run.

## One-command local run (backend + audio agent + saved logs)
```bash
./scripts/run_local_audio_console.sh
```

This creates a per-run folder:
- `local-observability/run-<timestamp>/`

Artifacts saved there:
- `backend.log.jsonl`
- `backend.tools.jsonl`
- `backend.stdout.log`
- `session-reports/*.json`
- `agent.log.jsonl`

Console recordings (from `--record`) go to:
- `console-recordings/`

## Key fixes that prevent “stuck” local runs
- **Vehicle description accepted:** if the caller says a vehicle description (e.g. “blue truck”) instead of a VIN/unit number, we save it as a `unit_nickname` so the flow can move on.
- **Env clarity:** `/health/env` reports whether key env vars are configured (no secrets exposed).

## Useful quick checks
- Backend env presence (no secrets):
```bash
curl -sS http://127.0.0.1:8000/health/env | jq .
```

## Advanced knobs
You can override these at invocation time:
- Backend-first vs OpenAI-first:
  - `AGENT_BACKEND_GUARDRAILS=true` (default): call `get_case_status` on every user turn.
  - `AGENT_BACKEND_GUARDRAILS=false`: let OpenAI drive, calling tools only when needed.

## Canonical doc
The detailed guide lives at:
- `docs/documentations/localdebug.md`
