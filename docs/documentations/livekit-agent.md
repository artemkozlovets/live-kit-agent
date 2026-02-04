# LiveKit Agent (Codex Context)

> **Last Updated**: 2026-02-03  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `livekit_agent/` runs the LiveKit Agents worker.
- **Conversation engine:** OpenAI Realtime.
- **Backend tools contract:** agent calls `POST /tools` (v2) with auth header `X-TOOLS-TOKEN` (env `TOOLS_TOKEN`).
- **How to verify:** `./scripts/test_all.sh`

## Key files (start here)
- Worker entrypoint: `livekit_agent/agent.py`
- OpenAI Realtime agent logic (backend-first turn hook + tool forwarding): `livekit_agent/openai_realtime_agent.py`
- OpenAI Realtime session factory (plugin import is lazy): `livekit_agent/openai_realtime_session.py`
- Backend HTTP client + v2 result parsing: `livekit_agent/backend_tools_client.py`
- Tools v2 payload builder: `livekit_agent/tools_v2_payload.py`
- OpenAI Realtime audio smoke test (no mic): `livekit_agent/openai_realtime_audio_smoke.py`

## Prompt / instructions (OpenAI Realtime)
- **Runtime instructions live in code**: the Realtime agent uses the `instructions=...` string in
  `livekit_agent/openai_realtime_agent.py`.
- `squad/assistants/*.prompt.md` define intended flows and tools, but are **not loaded** by the
  OpenAI Realtime agent at runtime. Update the runtime instructions if behavior needs tightening.

Language behavior (runtime):
- Default: **English-only** responses.
- If the caller speaks Spanish, the agent asks: “Would you prefer to speak in Spanish?” and only switches after an explicit confirmation.

## Runtime flow (happy path)
1. LiveKit starts the agent worker (`python -m livekit_agent.agent ...`).
2. `livekit_agent/agent.py` builds an OpenAI Realtime `AgentSession` and starts `OpenAIRealtimeAgent`.
3. During conversation:
   - Agent calls backend `get_case_status(last_user_message=...)` on each user turn.
   - Most tool calls are forwarded to the backend via `BackendToolsClient.call_tool(...)`.
   - Some tools are local-only (example: `transfer_to_human` performs a SIP transfer via the LiveKit API).

## Realtime turn-taking (important)
- We explicitly disable OpenAI Realtime **auto response generation** (`turn_detection.create_response=false`) so the model does **not** speak on VAD events before our backend-first guardrails run.
  - All speech is triggered by our code calling `session.generate_reply(...)` (greeting + user turns).
  - See [`build_openai_realtime_session`](../../livekit_agent/openai_realtime_session.py#L40-L109).
- We also disable OpenAI Realtime **auto interruption** (`turn_detection.interrupt_response=false`) to reduce false barge-ins / echo cutting off speech.
- We attempt to schedule inbound phone greeting with `allow_interruptions=False` to reduce early echo/false barge-ins cutting off the first words.
  - Note: LiveKit Agents may ignore `allow_interruptions=False` when using server-side turn detection.

### Critical gotcha: Realtime turn detection vs `on_user_turn_completed`
This repo’s backend-first turn logic depends on `OpenAIRealtimeAgent.on_user_turn_completed()` to:
- call backend `get_case_status(...)`, then
- trigger the next assistant response via `session.generate_reply(...)`.

**Important:** LiveKit’s docs note that to use `on_user_turn_completed()` with a realtime model, **turn detection must occur in your agent instead of within the realtime model**.

If OpenAI Realtime is doing turn detection and we also set `turn_detection.create_response=false`, you can end up in a state where:
- the user’s speech is transcribed, but
- the agent never starts a follow-up response,
so the call feels “stuck” (commonly reported as “it hangs after I say my phone number”).

**How to spot this in logs (fast):**
- With `VOICE_DEBUG=1`, look for `VOICE_DEBUG user_input_transcribed` and `VOICE_DEBUG conversation_item_added` (role=`user`) **without** a later `VOICE_DEBUG speech_created`.

**Where this behavior lives:**
- Realtime session config (auto response disabled): [`livekit_agent/openai_realtime_session.py`](../../livekit_agent/openai_realtime_session.py#L60-L87)
- Turn loop (backend-first + reply trigger): [`OpenAIRealtimeAgent._handle_user_text_turn`](../../livekit_agent/openai_realtime_agent.py#L770)
- Turn hook (when it fires): [`OpenAIRealtimeAgent.on_user_turn_completed`](../../livekit_agent/openai_realtime_agent.py#L1096)
- Transcript-driven fallback (when `on_user_turn_completed` does not fire): [`OpenAIRealtimeAgent._install_realtime_transcript_listener`](../../livekit_agent/openai_realtime_agent.py#L584) and [`OpenAIRealtimeAgent._maybe_handle_realtime_user_text_turn`](../../livekit_agent/openai_realtime_agent.py#L689)

External references:
- LiveKit Agents “Pipeline nodes and hooks” (`on_user_turn_completed` note): https://docs.livekit.io/agents/logic/nodes/#on_user_turn_completed
- LiveKit Agents “Turn detection & interruptions”: https://docs.livekit.io/agents/logic/turns/
- LiveKit OpenAI Realtime plugin guide (turn detection options): https://docs.livekit.io/agents/models/realtime/plugins/openai/#turn-detection
- OpenAI “Realtime conversations” (`create_response=false`): https://platform.openai.com/docs/guides/realtime-conversations#keep-vad-but-disable-automatic-responses

### Critical gotcha: `generate_reply(user_input=...)` can duplicate realtime transcripts
In realtime audio sessions, LiveKit can commit `user_input_transcribed(is_final=true)` into the chat history as a `user` message.

If we then call `session.generate_reply(user_input="...")` for the same transcript, the user message can be added **twice**, which causes:
- “echo-y” conversations (model repeats itself),
- unexpected re-asking for already-provided info (phone/name), and
- faster context bloat (more unstable behavior over longer calls).

This can happen from either trigger:
- the transcript-driven fallback (`user_input_transcribed`), or
- `on_user_turn_completed` (when it fires in a realtime session).

**Fix:** for realtime sessions, call `generate_reply(...)` **without** `user_input` on turn triggers where the user message is already in history, and pass backend guidance via per-turn `instructions`.

Repo refs:
- `livekit_agent/openai_realtime_agent.py` (transcript turn path + `generate_reply` call)
- Regression tests:
  - `livekit_agent/tests/test_openai_realtime_agent_realtime_transcript_no_user_input_when_llm_present.py`
  - `livekit_agent/tests/test_openai_realtime_agent_turn_hook_no_user_input_when_llm_present.py`

## Contract: backend tools (v2)
- **URL:** `BACKEND_TOOLS_URL` (default ends with `/tools`)
- **Auth:** header `X-TOOLS-TOKEN` must equal env `TOOLS_TOKEN`
- **Response correlation:** results match by `tool_call_id`

See `docs/documentations/api-server.md` for the full `/tools` contract and failure semantics.

### Booking confirmation (must-not-break)
- The backend enforces **no booking without explicit confirmation**:
  - `store_service_order` before confirmation returns `booking_not_confirmed` (HTTP 200, `ok=false`).
- In the LiveKit agent, tool-call failures should return a **structured tool result** (not raise) so the model can recover instead of seeing a generic “internal error”.
  - Regression: `livekit_agent/tests/test_openai_realtime_agent_forward_tool_booking_not_confirmed.py`

## Configuration (env vars)

### Required (default OpenAI Realtime path)
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `BACKEND_TOOLS_URL` (should end with `/tools`)
- `TOOLS_TOKEN` (shared secret for `X-TOOLS-TOKEN`)
- `OPENAI_API_KEY`

Optional:
- `OPENAI_REALTIME_VOICE` (passed to `openai.realtime.RealtimeModel(...)`)
- `OPENAI_REALTIME_EAGERNESS` (`auto|low|medium|high`; semantic VAD eagerness; lower = less interrupting)
- `AGENT_BACKEND_GUARDRAILS` (defaults to `true`; set to `false` to let the model manage the flow without calling `get_case_status` every turn)
- `SESSION_REPORTS_URL` + `SESSION_REPORTS_TOKEN` (optional: publish session reports at session end)
- `HUMAN_TRANSFER_TO` (optional: `tel:+...` transfer target for `transfer_to_human`)
- `REALTIME_TRANSCRIPT_DEBOUNCE_S` (debounce final transcript bursts before triggering the backend-first reply loop; default `0.25`)
- `REALTIME_TRANSCRIPT_POST_SILENCE_S` (minimum stable “user stopped speaking” time before triggering a reply; default `0.3`)
- `REALTIME_TRANSCRIPT_MAX_WAIT_S` (max time to wait for user to stop speaking before replying; default `8.0`)
- `LK_MIN_INTERRUPTION_DURATION_S` (require at least N seconds of speech before interrupting the agent)
- `LK_MIN_INTERRUPTION_WORDS` (require at least N transcribed words before interrupting the agent)
- `LK_FALSE_INTERRUPTION_TIMEOUT_S` (how long to wait before treating an interruption as false; set `<0` to disable)
- `LK_RESUME_FALSE_INTERRUPTION` (`true|false`; whether to resume after a false interruption)

## Verification
- All tests: `./scripts/test_all.sh`
- Agent-only tests: `.venv/bin/python -m pytest -q livekit_agent/tests`

## Related docs
- `docs/specs/openai_realtime-spec.md`
- `docs/documentations/api-server.md`
- `docs/documentations/testing-and-evals.md`
- `docs/instructions/livekit-telephony-inbound-calls.md`
- `docs/documentations/realtime-human-transfer.md`
