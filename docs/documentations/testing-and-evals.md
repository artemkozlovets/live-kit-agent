# Testing + Evals (Codex Context)

> **Last Updated**: 2026-01-31  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- Fast unit tests (agent only): `python -m pytest -q`
- Full suite (agent + API server): `./scripts/test_all.sh`
- No-mic OpenAI “speaking” check (OpenAI-only): `./scripts/run_openai_realtime_audio_smoke.sh`
- No-mic “is this phone in the DB?” check (backend tools): `./scripts/run_openai_realtime_customer_lookup_smoke.sh --phone-number "..."`
- LiveKit Cloud end-to-end smoke (no browser; text + audio): `./scripts/run_livekit_cloud_smoke.sh`
- Smoke artifacts land under `local-observability/run-*-openai-realtime-*/` (WAV + JSON; ignored by default via [`.gitignore`](../../.gitignore))

## Definition of Done (Feature Work)
Treat smoke tests like “unit tests for deployments”:
- If you add/modify a user-visible behavior, add **at least one** smoke test that proves it works.
- Run:
  1) `python -m pytest -q` (fast)
  2) the smallest relevant smoke(s) locally (no mic)
  3) after deploy: `./scripts/run_livekit_cloud_smoke.sh` (remote, no browser)

## Pytest
By default, pytest is configured to run only `livekit_agent/tests`:
- Config: [`pytest.ini`](../../pytest.ini)

### Run agent tests (default)
```bash
python -m pytest -q
```

### Run all tests (agent + API server)
```bash
./scripts/test_all.sh
```

### Run API server tests
There is also a test suite under `api_server/tests/`, but it is not included in `pytest.ini`’s `testpaths`.

Run it explicitly:
```bash
python -m pytest -q api_server/tests
```

## Smoke Tests (No Mic)
Big picture: “smoke tests” here are **CLI scripts** that:
- avoid microphone/device permissions (scripted inputs),
- fail fast with an exit code, and
- save durable artifacts (WAV + JSON) so you can compare runs later.

If you see `sysctlbyname('hw.logicalcpu') Operation not permitted`, set `NUM_CPUS=2` in your environment.

> Note: These scripts do **not** auto-load `.env`. Export env vars in your shell first
> (or use `direnv`).
>
> Example (bash/zsh):
> ```bash
> set -a && source .env && set +a
> ```

### 1) OpenAI Realtime Audio Smoke (OpenAI-only)
**Goal:** verify the OpenAI Realtime plugin produces **audio output** (no backend calls).

**Entry points**
- Wrapper: [`scripts/run_openai_realtime_audio_smoke.sh`](../../scripts/run_openai_realtime_audio_smoke.sh)
- Runner: [`livekit_agent/openai_realtime_audio_smoke.py`](../../livekit_agent/openai_realtime_audio_smoke.py)
- WAV sink: [`livekit_agent/audio_output_wav.py`](../../livekit_agent/audio_output_wav.py)

**Inputs**
- Env: `OPENAI_API_KEY` (required)
- Flags:
  - `--turn "..."` (repeatable) or `--turns-file turns.txt` (one turn per line)
  - `--voice <voice>` (optional; defaults to `OPENAI_REALTIME_VOICE`)
  - `--modalities "text,audio"` (default) or `"text"` (text-only)
  - `--timeout-s 60` (per turn)

**Run**
```bash
./scripts/run_openai_realtime_audio_smoke.sh \
  --turn "Please say: 'OpenAI realtime audio smoke test OK.'" \
  --modalities "text,audio"
```

**Outputs**
- Directory: `local-observability/run-*-openai-realtime-audio-smoke/`
- Files:
  - `assistant.wav` — the agent’s spoken output
  - `transcript.json` — user/assistant text + segment boundaries
  - `meta.json` — run config + audio stats

**Exit codes**
- `0`: audio was captured
- `2`: no audio frames were captured (common causes: missing `audio` in modalities, invalid voice)
- `1`: crash/misconfig (missing API key, network error, etc.)

**How to verify quickly**
- Open the WAV (macOS): `open local-observability/run-*-openai-realtime-audio-smoke/assistant.wav`
- Or inspect `meta.json` for `total_samples > 0`.

**Known log noise (safe to ignore)**
- `resume_false_interruption is enabled but audio output does not support pause, it will be ignored`

**Common failure messages**
- `ERROR: OPENAI_API_KEY is required.` → your shell doesn’t have `OPENAI_API_KEY` exported.
- `OpenAI Realtime plugin not installed...` → install extras: `pip install "livekit-agents[openai]"`
- `ERROR: No audio frames were captured...` → `--modalities` likely missing `audio`, or the selected `--voice` is invalid.

### 2) Customer Lookup Smoke (Backend DB + optional OpenAI audio)
**Goal:** verify a phone number is (or isn’t) in the DB by calling the backend tools:
1) `validate_phone(phone_number=...)`
2) `check_customer(phone_number=...)`

Optionally, it also generates an OpenAI Realtime audio response (`assistant.wav`) so you can confirm speech still works.

**Entry points**
- Wrapper: [`scripts/run_openai_realtime_customer_lookup_smoke.sh`](../../scripts/run_openai_realtime_customer_lookup_smoke.sh)
- Runner: [`livekit_agent/openai_realtime_customer_lookup_smoke.py`](../../livekit_agent/openai_realtime_customer_lookup_smoke.py)
- Backend client: [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py)
- Backend contract: [`docs/documentations/api-server.md`](./api-server.md)

**Inputs**
- Required:
  - `--phone-number "305 555 0123"` (any formatting; backend normalizes to `+1##########`)
  - backend auth: `TOOLS_TOKEN` (env or `--tools-token`)
- Backend URL:
  - `BACKEND_TOOLS_URL` (env) or `--backend-tools-url` (must end in `/tools`)
  - If unset, it defaults to the repo’s dev backend URL.
- Optional:
  - `--expect-found true|false` (default: `true`)
  - `--with-audio true|false` (default: `true`)
  - If `--with-audio true`: `OPENAI_API_KEY` is required.

**Run (DB check + audio)**
```bash
./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "305 555 0123" \
  --expect-found true
```

**Run (DB check only; no OpenAI call)**
```bash
./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "305 555 0123" \
  --expect-found true \
  --with-audio false
```

**If it fails with `TOOLS_TOKEN is required for /tools`**
- Ensure `TOOLS_TOKEN` is set in your environment or provided via `--tools-token`.
- If you’re relying on Railway secrets, run via `railway run --service ...` so the env is injected.

**Outputs**
- Directory: `local-observability/run-*-openai-realtime-customer-lookup-smoke/`
- Files:
  - `validate_phone.json` — shows the normalized/E.164 number used for lookup
  - `check_customer.json` — contains `found: true|false` and `customer` when found
  - `result.json` — `{ ok, expected_found, found, customer }`
  - `assistant.wav` — only when `--with-audio true`

**Exit codes**
- `0`: `found == expected_found`
- `2`: mismatch (ex: expected found, but backend returned `found: false`)
- `1`: crash/misconfig (missing token, backend unreachable, etc.)

**Common failure messages**
- `TOOLS_TOKEN is required for /tools` → set `TOOLS_TOKEN` (or pass `--tools-token`).
- `Backend responded with HTTP 401...` → `TOOLS_TOKEN` is wrong for that backend.
- `Backend connection failed` → `BACKEND_TOOLS_URL` is wrong/unreachable.

**Running against Railway without exporting secrets**
If your Railway backend service has `TOOLS_TOKEN` and `BACKEND_TOOLS_URL` set, you can inject them into the command with `railway run`:
```bash
railway run --service "Call-agent" --environment development \
  ./scripts/run_openai_realtime_customer_lookup_smoke.sh \
  --phone-number "305 555 0123" \
  --with-audio false
```

## Adding a New Smoke Test (Pattern)
When you add more smoke tests later, follow these conventions:
- **No mic by default:** prefer scripted text input (or deterministic audio files), not live microphone capture.
- **Artifacts + exit codes:** always write a `result.json` with a single `ok` boolean and return `0/2/1` (pass/mismatch/crash).
- **Keep artifacts ignored:** write to `local-observability/run-<timestamp>-<test-name>/` so `.gitignore` excludes it.
- **Backend checks use `/tools`:** call tools via `BackendToolsClient.call_tool(...)` rather than hand-rolling HTTP.
- **Realtime audio capture:** attach `WavFileAudioOutput` to `session.output.audio` before `await session.start(...)` and write a WAV.

## LiveKit Cloud Smoke (No Browser)
This is the closest thing to “unit tests for a deployment”:
- It runs against the **deployed LiveKit Cloud agent** via `lk` (no browser required).
- It asserts on the **session report** exported by the backend (`/observability/session-report`).

**Entry points**
- Wrapper: [`scripts/run_livekit_cloud_smoke.sh`](../../scripts/run_livekit_cloud_smoke.sh)
- Runner: [`scripts/livekit_cloud_smoke.py`](../../scripts/livekit_cloud_smoke.py)
- Session reports pipeline: [`docs/documentations/debug.md`](./debug.md)

**Prereqs**
- `lk` CLI is authenticated + points at the right project/agent (`cat livekit.toml`).
- Session report ingest is configured for the deployed agent (`SESSION_REPORTS_URL` secret).

**Run**
```bash
# text turn → assistant reply
./scripts/run_livekit_cloud_smoke.sh --scenario text

# publish Ogg Opus → final transcript → assistant reply
./scripts/run_livekit_cloud_smoke.sh --scenario audio

# frustration + confirmation → transfer_to_human tool call (no telephony in this room)
./scripts/run_livekit_cloud_smoke.sh --scenario transfer

# both (default)
./scripts/run_livekit_cloud_smoke.sh
```

**Run via pytest (optional; “unit test style”)**
```bash
RUN_LIVEKIT_CLOUD_SMOKE=1 python -m pytest -q livekit_agent/tests/test_livekit_cloud_smoke_optional.py
```

**Outputs**
- Directory: `local-observability/run-*-livekit-cloud-smoke/`
- Files:
  - `result.json` (overall pass/fail)
  - `text/session_report.json`
  - `audio/session_report.json`
  - `transfer/session_report.json`
  - `audio/lk_room_join.log` (debugging the publish step)

**Common failures**
- `did_not_find_final_transcript` → audio didn’t produce a final transcript (codec/VAD/transcription) or the publish participant disconnected too early.
- `no_assistant_reply_after_transcript` → transcription happened but Realtime didn’t reply (OpenAI session failure, tool loop issues, etc.).
- `did_not_call_transfer_to_human` → model didn’t call the local transfer tool (prompt nondeterminism; inspect the report + adjust transfer turns).
- `401/403` while polling reports → session report endpoint is protected; export `SESSION_REPORTS_TOKEN` before running.

## Related Docs
- [`docs/documentations/localdebug.md`](./localdebug.md) (local workflows + artifacts)
- [`docs/instructions/openai-realtime-rollout.md`](../instructions/openai-realtime-rollout.md) (smoke + rollback checklist)
- [`docs/documentations/api-server.md`](./api-server.md) (`POST /tools` contract + auth)
