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
- **Gemini extraction fallback:** if Gemini extraction fails, `get_case_status` can fall back to the deterministic extractor when `GET_CASE_STATUS_FAST_EXTRACTOR=1`.
- **Vehicle description accepted:** if the caller says a vehicle description (e.g. “blue truck”) instead of a VIN/unit number, we save it as a `unit_nickname` so the flow can move on.
- **Env clarity:** `/health/env` now treats `GOOGLE_API_KEY` as satisfying the “Gemini API key loaded” check (no secrets exposed).

## Useful quick checks
- Backend env presence (no secrets):
```bash
curl -sS http://127.0.0.1:8000/health/env | jq .
```

## Advanced knobs
You can override these at invocation time:
- Use Gemini inside `get_case_status` (slower, networked):
  - `GET_CASE_STATUS_GEMINI_CLASSIFICATION=1`
  - `GET_CASE_STATUS_GEMINI_EXTRACTION=1`
  - `GET_CASE_STATUS_GEMINI_CORRECTIONS=1`
- Disable “fast intake” and use the legacy callback-number preflight:
  - `AGENT_FAST_INTAKE=0`

## Canonical doc
The detailed guide lives at:
- `docs/documentations/localdebug.md`
