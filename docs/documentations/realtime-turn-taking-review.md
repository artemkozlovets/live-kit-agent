# OpenAI Realtime Turn-Taking Review (LiveKit Agent)

> **Last Updated**: 2026-02-03  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## Big picture
This repo runs a LiveKit Agents voice worker that uses **OpenAI Realtime** as the conversation engine and a separate FastAPI backend that exposes a provider-agnostic tools endpoint (`POST /tools`).

The agent intentionally disables OpenAI Realtime’s automatic response creation (`turn_detection.create_response=false`) so it can run a **backend-first** guardrail/tool step (typically `get_case_status`) *before* speaking.

Implication: **if nothing calls `session.generate_reply(...)`, the agent will stay silent**.

Key code:
- Agent runtime: `livekit_agent/openai_realtime_agent.py`
- Realtime session config: `livekit_agent/openai_realtime_session.py`
- Backend tools client + v2 parsing: `livekit_agent/backend_tools_client.py`
- Tools v2 request builder: `livekit_agent/tools_v2_payload.py`
- Backend `/tools` router: `api_server/tools/router.py`

## Turn-taking correctness (who triggers replies)
In the normal call flow, the agent speaks in two ways:
1) **Greeting** (telephony only): `OpenAIRealtimeAgent.on_enter()` schedules `session.generate_reply(...)`.
2) **User turns** (backend-first loop): something must call the per-turn handler which:
   - calls backend `get_case_status(last_user_message=...)`, then
   - calls `session.generate_reply(...)` (with authoritative JSON injected via per-turn `instructions`).

There is also a **failure-path fallback** when the backend is unreachable:
- `OpenAIRealtimeAgent._speak_backend_unreachable_once()` calls `session.say(...)` (see “Failure modes” below for a Realtime caveat).

There are **two turn triggers**:
- **Preferred (when available):** `OpenAIRealtimeAgent.on_user_turn_completed(...)`
- **Fallback (realtime audio gotcha):** debounced `user_input_transcribed(is_final=true)` listener

Why the fallback exists:
- LiveKit docs: to use `on_user_turn_completed` with a realtime model, **turn detection must occur in your agent** (not inside the realtime model).  
- This repo uses OpenAI Realtime’s built-in turn detection (`RealtimeModel(turn_detection=...)`), so `on_user_turn_completed` may not fire for audio turns and we must trigger from transcripts.

Repo doc refs:
- `docs/documentations/livekit-agent.md` (turn-detection gotchas)
- `docs/documentations/voice-interruptions.md` (final transcript bursts + silence gating)

## Double-trigger / race condition analysis
### What the repo already does (good)
The transcript-driven fallback is intentionally defensive:
- Debounces bursty finals (`REALTIME_TRANSCRIPT_DEBOUNCE_S`).
- Waits for a stable “not speaking” state before replying (`REALTIME_TRANSCRIPT_POST_SILENCE_S`, bounded by `REALTIME_TRANSCRIPT_MAX_WAIT_S`).
- Cancels pending transcript tasks when `on_user_turn_completed` fires (`_cancel_pending_realtime_user_text_turn`).
- Avoids replying twice when `on_user_turn_completed` already processed a newer turn (created_at checks).
- Avoids duplicate chat history entries by *not* passing `user_input` when the transcript is already in the conversation history (Realtime session path):
  - `user_message_already_in_history=True` + “LLM present” ⇒ `generate_reply(chat_ctx=..., instructions=...)` **without** `user_input=...`.

Tests that cover these behaviors:
- `livekit_agent/tests/test_openai_realtime_agent_realtime_transcript_turn_trigger.py`
- `livekit_agent/tests/test_openai_realtime_agent_realtime_transcript_debounce.py`
- `livekit_agent/tests/test_openai_realtime_agent_realtime_transcript_no_user_input_when_llm_present.py`

### Remaining risks (still possible)
1) **True double replies** if both triggers run for the same utterance:
   - If the transcript fallback already started generating a reply and then `on_user_turn_completed` fires later, cancellation won’t stop the already-running handler.
   - The transcript path serializes itself (`_realtime_turn_lock`), but `on_user_turn_completed` does not share that lock, so both paths can overlap in time.

2) **`created_at` mismatch / missing timestamp edge cases**:
   - Transcript events without a usable `created_at` fall back to a short wallclock window (`0.25s`) to avoid double triggers.
   - If the turn hook arrives later than that window (but still “the same turn”), the fallback may already have replied.
   - If one path uses wallclock while the other uses event timestamps from a different clock domain, comparisons can become meaningless.

3) **Late “final transcript corrections”**:
   - Some realtime pipelines can emit more than one “final” transcript for a single perceived user turn (corrections or chunking).
   - If a later final arrives after the fallback already replied (and user_state is no longer `speaking`), it can be treated as a new turn and trigger a second reply.

### Refactor-friendly mitigation (keeps behavior)
If this becomes a practical issue in production, the cleanest fix is to make turn handling **idempotent + serialized**:
- Use one shared lock for **both** `on_user_turn_completed` and transcript fallback.
- Create a single “turn key” (best available: conversation item id / speech id; fallback: `created_at + transcript_hash`).
- Maintain `last_handled_turn_key` (and/or a small LRU of recent keys) to drop duplicates across trigger sources.

## Debounce + “wait until user not speaking” heuristic (soundness)
The current heuristic is directionally correct for the known failure mode:
- Realtime can produce bursty “final” transcripts mid-utterance.
- Replying immediately causes overlap → interruptions → “rigid workflow while caller is still talking”.

The wait loop is also bounded (`REALTIME_TRANSCRIPT_MAX_WAIT_S`) so it can’t hang forever.

Suggested refinement (if you need fewer false triggers without adding much complexity):
- Also gate on **agent state**: don’t schedule a new reply if the agent is already `speaking` or `thinking` unless you explicitly want to interrupt/replace.
- Consider using `conversation_item_added(role="user")` as the fallback trigger when it’s available, since it aligns with what actually enters the chat history (and makes “duplicate user_input” easier to reason about).

## Chat context vs per-turn instructions (Realtime quirk)
This repo injects backend guidance twice:
- Adds `{"case_status": ...}` as a system message in `ChatContext`, and
- Duplicates the same JSON inside per-turn `instructions`

Reason (in code): OpenAI Realtime sessions may not consume `chat_ctx` passed to `generate_reply`, so `instructions` is used as the reliable delivery mechanism.

Pragmatic take:
- This is robust *today* (it ensures the model sees the guidance).
- If the Realtime plugin starts honoring `chat_ctx` in the future, this could become redundant and slightly increase prompt noise.

If you ever observe the model reacting poorly to “duplicate guidance”, prefer one canonical injection path:
- **Best (if supported):** update the realtime conversation state explicitly (LiveKit `update_chat_ctx` / provider session update), then call `generate_reply` without repeating JSON in `instructions`.
- **Fallback:** keep `instructions` only, and drop the `ChatContext` system message (but keep it in tests if it improves determinism).

## Interruption configuration (barge-in vs false interruptions)
Current choices:
- OpenAI Realtime VAD enabled (semantic VAD), but:
  - `turn_detection.create_response=false` (manual reply trigger)
  - `turn_detection.interrupt_response=false` (reduce auto-interrupt)
- Greeting uses `allow_interruptions=False`, but LiveKit docs note `allow_interruptions` may be **ignored** with a realtime model’s built-in turn detection.

Risk:
- Disabling `interrupt_response` globally can make the agent feel “hard to interrupt”, especially if responses run long.

Recommended alternative that still avoids false interruptions:
- Keep semantic VAD with `OPENAI_REALTIME_EAGERNESS=low`, but consider setting `interrupt_response=true` after the greeting (or in non-telephony contexts).
- Use LiveKit session knobs to reduce false interruptions:
  - `LK_MIN_INTERRUPTION_DURATION_S`
  - `LK_FALSE_INTERRUPTION_TIMEOUT_S` + `LK_RESUME_FALSE_INTERRUPTION`
  - Keep `LK_DISCARD_AUDIO_IF_UNINTERRUPTIBLE=false` for PSTN greeting “first words” safety.

OpenAI VAD doc ref: `https://platform.openai.com/docs/guides/realtime-vad`

## Greeting echo/self-talk filter (speakerphone feedback)
Current implementation:
- After scheduling the greeting, the agent stores a normalized expected transcript.
- If a final transcript matches within a short window, it is ignored (prevents “agent talks to itself” loops).

This is a good baseline, but it is intentionally conservative:
- It catches “exact echo” of the greeting.
- It won’t catch partial echoes or paraphrases (common on noisy speakerphone).

If echo/self-talk is still common, stronger strategies (in increasing complexity) include:
- Fuzzy similarity threshold (token overlap) instead of exact match.
- Ignore transcripts that occur while the agent is mid-greeting speech window (based on `speech_created`/`speech_done` events).
- Reduce echo at the source (PSTN audio path, user instructions, or client echo cancellation).

## Backend-first `get_case_status` on every turn (is it optimal?)
Benefits:
- Backend remains authoritative for session state + validation + booking safety.
- Agent logic stays simple (“always ask backend what’s true”).

Costs:
- Adds dead air equal to `/tools` latency on every user turn.
- Increases failure blast radius (backend down ⇒ call becomes unrecoverable).

The agent already gates at least one category:
- “Language control” messages can respond with “Do not call any tools.”

Low-risk optimizations that preserve backend-first behavior:
- **Micro-cache** `get_case_status` for a short TTL (e.g., 0.5–1.0s) to avoid repeat calls during transcript bursts.
- **Prefetch while waiting for silence** (start backend call right after the first final transcript; only speak after quiet window).
- **Skip backend calls for clearly non-semantic backchannels** (“mm-hmm”, “okay”, “right”) unless the backend indicates you’re in a confirmation phase.

## Failure modes to be aware of
- **Backend unreachable:** agent sets a fatal flag and attempts a one-time fallback message.
  - Verify this fallback is actually audible in realtime sessions (LiveKit docs note `session.say()` requires a TTS plugin; for pure realtime sessions you may need `generate_reply(instructions=...)` instead).
  - Test: `livekit_agent/tests/test_openai_realtime_agent_step_3_backend_down.py`
- **Stuck turn / silence:** create_response=false + no reply trigger ⇒ silence after user speaks.
  - Debug: look for `VOICE_DEBUG user_input_transcribed` without later `VOICE_DEBUG speech_created`.
- **Double-trigger / “two agents” feeling:** overlap between hook path and transcript fallback, or repeated “final” transcript chunks treated as new turns.
- **Echo/self-talk:** speakerphone feedback; greeting transcript can re-enter as user input despite guard.
- **Transfer failures:** LiveKit Phone Numbers may not support SIP transfers (tool returns `transfer_not_supported`).
- **Backend state loss:** tools backend uses an in-memory session store keyed by `call.id`; restarts/replicas can lose continuity.

## Observability (what to log/measure)
Existing high-signal sources:
- `VOICE_DEBUG=1` on agent: `livekit_agent/voice_debug.py`
  - correlate: `user_input_transcribed` → `backend_tool_ok` → `speech_created` → `speech_done`
- Backend per-request JSONL (optional): `LOCAL_OBSERVABILITY_DIR` → `backend.tools.jsonl`
- Session reports (best post-call artifact): `SESSION_REPORTS_URL` pipeline

When chasing turn-taking bugs, capture:
- The trigger source (`on_user_turn_completed` vs transcript fallback)
- Turn correlation fields (`created_at`, transcript hash, and if available a conversation item id)
- Backend timing (`backend_tool_* elapsed_ms`)

## Direct answers to the 8 review questions
1) **Double replies risk?** Mostly mitigated (cancellation + created_at checks), but still possible if both triggers execute concurrently or if timestamps are missing/skewed. The paths don’t share a lock.
2) **Debounce + “wait until not speaking” sound?** Yes; it matches the known “final transcript bursts” issue. Add agent-state gating if you still see early replies.
3) **created_at==0 / wallclock fallback races?** The `0.25s` wallclock gate is a best-effort band-aid; if timestamps are missing or come from different clock domains, duplicates can slip through (or legitimate turns can be suppressed).
4) **Duplicating JSON in instructions robust?** It’s robust today (ensures the model sees it), but could become redundant if the realtime plugin starts consuming `chat_ctx`. Prefer one canonical injection path if/when possible.
5) **interrupt_response=false too much?** It can reduce barge-in. Consider enabling interrupts after greeting (or rely on LiveKit interruption heuristics) while keeping `OPENAI_REALTIME_EAGERNESS=low` to reduce false triggers.
6) **Greeting echo filter sufficient?** Good baseline for exact echo; doesn’t catch partial echoes. Consider fuzzy matching + gating during the greeting speech window if self-talk persists.
7) **Always calling get_case_status optimal?** Simple and safe, but adds latency and increases dependency on backend uptime. Consider TTL caching or prefetching during silence waits.
8) **Refactor ideas?** Consolidate both triggers behind a single serialized “turn orchestrator” with idempotency keys and explicit trigger-source logging.
