# Voice Interruptions + “Rigid Workflow While Caller Is Speaking”

> **Last Updated**: 2026-02-03  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## Big picture
Two different problems often get conflated:

1. **Interrupting / cut‑offs**: the assistant starts speaking, then gets cut off mid‑sentence.
2. **“Rigid workflow” while caller is still talking**: the assistant starts asking questions or responding before the caller has finished their thought.

In practice, (2) can *cause* (1): if we trigger a reply too early, the caller continues speaking and the agent is immediately “interrupted”.

## How to confirm (session reports)
This repo can ingest LiveKit Agent **session reports** at `POST /observability/session-report` and store them for debugging.

To fetch the latest reports (no UI):
```bash
./scripts/fetch_session_reports.py \
  --url "https://<your-railway-domain>/observability/session-report" \
  --limit 10
```

When looking at a specific report, the most useful signals are:
- `report.chat_history.items[]`:
  - Assistant messages can include `interrupted: true` (means the agent speech was cut off).
- `report.events[]`:
  - `user_state_changed` + `agent_state_changed` sequences (who was speaking when).
  - `user_input_transcribed` events (when “final” transcripts arrive).

Quick local analysis helper (no PII printing):
```bash
python - <<'PY'
import json, urllib.request, urllib.parse
BASE="https://<your-railway-domain>/observability/session-report"
ROOM="<room_name>"
url=BASE.rstrip("/")+"/"+urllib.parse.quote(ROOM,safe="")
with urllib.request.urlopen(url, timeout=15) as resp:
    payload=json.load(resp)
report=payload.get("report") or {}

items=(report.get("chat_history") or {}).get("items") or []
assistant_msgs=[i for i in items if isinstance(i,dict) and i.get("type")=="message" and i.get("role")=="assistant"]
interrupted=sum(1 for i in assistant_msgs if i.get("interrupted") is True)
print("assistant_msgs",len(assistant_msgs),"interrupted",interrupted)

events=report.get("events") or []
types={}
for ev in events:
    if isinstance(ev,dict):
        types[ev.get("type")]=types.get(ev.get("type"),0)+1
print("event_type_counts",sorted(types.items(), key=lambda kv: kv[0]))
PY
```

## Root causes (common)

### A) Echo / speakerphone feedback (most common for PSTN)
**Symptom**
- Sounds like the agent is “talking to itself”, interrupting constantly, or the conversation is choppy.

**Why**
- On speakerphone, the phone mic can pick up the agent’s own audio. With VAD + interruption handling, that echo can be treated as new user speech, so the agent gets interrupted over and over.

**Fix**
- Use handset earpiece or headphones; avoid speakerphone.
- Reduce volume / separate mic from speaker if hands‑free is unavoidable.

Repo refs:
- `docs/instructions/livekit-telephony-inbound-calls.md`
- `docs/documentations/debug.md`

### B) “Final transcript bursts” mid‑turn (repo-specific)
**Symptom**
- Agent responds while the caller is still talking (feels rigid / cuts off the caller).
- Session reports show assistant messages marked `interrupted: true`, and agent speech starting while `user_state=speaking`.

**Why**
- With OpenAI Realtime, `user_input_transcribed(is_final=true)` can arrive multiple times before the user’s turn is truly complete.
- This repo uses a transcript-driven fallback to trigger the backend-first reply loop when `on_user_turn_completed` doesn’t fire for realtime turn detection.
- If we treat every “final transcript” as a complete turn, we can trigger `generate_reply(...)` too early (mid-utterance), which creates overlap and repeated interruptions.

**Fix (implemented 2026-02-02)**
- Debounce final transcript events and wait for stable `user_state=listening` before triggering the backend-first reply loop.

Code refs:
- `livekit_agent/openai_realtime_agent.py` (`_queue_realtime_user_text_turn`, `_maybe_handle_realtime_user_text_turn`)
- Tuning env vars: `REALTIME_TRANSCRIPT_DEBOUNCE_S`, `REALTIME_TRANSCRIPT_POST_SILENCE_S`, `REALTIME_TRANSCRIPT_MAX_WAIT_S`

### C) Duplicate user turns (realtime transcript + `user_input`) (repo-specific)
**Symptom**
- The model repeats itself, “forgets” it already has phone/name, or behaves inconsistently.
- Session reports show the *same* user utterance added twice to chat history.
  - Example pattern in `report.events[]`:
    - `user_input_transcribed(is_final=true, transcript="...")`
    - `conversation_item_added(role="user", content="...")`
    - later (after `speech_created`): another `conversation_item_added(role="user", content="...")` with the same content.

**Why**
- LiveKit’s realtime pipeline already commits final transcripts into the chat history as a `user` message.
- Calling `session.generate_reply(user_input="...")` also appends a `user` message to chat history.
- If we trigger the backend-first reply loop from transcript events *and* pass `user_input`, the user turn is duplicated and the model sees it twice.

**Fix (implemented 2026-02-03)**
- When triggering a reply from a transcript-driven path, call `session.generate_reply(...)` **without** `user_input`.
  - Keep backend guidance visible via per-turn `instructions` (and optional `chat_ctx`).

Code refs:
- `livekit_agent/openai_realtime_agent.py` (`_handle_user_text_turn`, `_handle_realtime_user_text_turn`)
- Regression test: `livekit_agent/tests/test_openai_realtime_agent_realtime_transcript_no_user_input_when_llm_present.py`

### D) Turn detection / interruption sensitivity too aggressive
Even with the repo-level fix above, noisy environments can still cause too many interruptions.

Recommended knobs:
- OpenAI semantic VAD eagerness:
  - `OPENAI_REALTIME_EAGERNESS=low|medium|high|auto` (lower = waits longer; less interrupting).
- LiveKit Agents session interruption heuristics:
  - `LK_MIN_INTERRUPTION_DURATION_S` (require at least N seconds of speech before interrupting)
  - `LK_MIN_INTERRUPTION_WORDS` (require at least N transcribed words before interrupting)
  - `LK_FALSE_INTERRUPTION_TIMEOUT_S` + `LK_RESUME_FALSE_INTERRUPTION` (false interruption handling)

Notes:
- LiveKit docs mention `allow_interruptions` can be ignored when using a realtime model with built-in turn detection. Prefer the knobs above for realtime calls.

## Recommended production defaults (PSTN)
Start with:
- `OPENAI_REALTIME_EAGERNESS=low`
- `REALTIME_TRANSCRIPT_DEBOUNCE_S=0.6`
- `REALTIME_TRANSCRIPT_POST_SILENCE_S=0.3`
- `REALTIME_TRANSCRIPT_MAX_WAIT_S=8.0`

If still too interrupt-y in noisy conditions:
- `LK_MIN_INTERRUPTION_DURATION_S=1.0`
- `LK_MIN_INTERRUPTION_WORDS=2`

## If it still feels “rigid”
This repo’s default is **backend-first guardrails** (`AGENT_BACKEND_GUARDRAILS=true`), which calls `get_case_status(...)` every turn and can feel more structured.

To compare behavior (diagnostic only):
- Set `AGENT_BACKEND_GUARDRAILS=false` and redeploy.
- If the rigidity disappears, the issue is likely the backend guardrail policy/tools guidance (not Realtime turn-taking).

## Deploy + validate
After changing any interruption-related code or tuning knobs:

1) Deploy the LiveKit Cloud agent:
```bash
lk agent deploy
lk agent status
```

2) Gate the deploy with the no-browser smoke test (text + audio):
```bash
./scripts/run_livekit_cloud_smoke.sh
```

3) If you still see interruptions, fetch the call’s session report and confirm:
- assistant messages have `interrupted: true`
- agent speech starts while `user_state=speaking` (overlap)

Runbook: `docs/instructions/deploy-livekit-cloud-agent.md`
