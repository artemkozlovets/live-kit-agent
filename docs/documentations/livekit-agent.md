# LiveKit Agent (Codex Context)

> **Last Updated**: 2026-01-31  
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

## Runtime flow (happy path)
1. LiveKit starts the agent worker (`python -m livekit_agent.agent ...`).
2. `livekit_agent/agent.py` builds an OpenAI Realtime `AgentSession` and starts `OpenAIRealtimeAgent`.
3. During conversation:
   - Agent calls backend `get_case_status(last_user_message=...)` on each user turn.
   - Tool calls are forwarded to the backend via `BackendToolsClient.call_tool(...)`.

## Realtime turn-taking (important)
- We explicitly disable OpenAI Realtime **auto response generation** (`turn_detection.create_response=false`) so the model does **not** speak on VAD events before our backend-first guardrails run.
  - All speech is triggered by our code calling `session.generate_reply(...)` (greeting + user turns).
  - See [`build_openai_realtime_session`](../../livekit_agent/openai_realtime_session.py#L8-L45).
- We also disable OpenAI Realtime **auto interruption** (`turn_detection.interrupt_response=false`) to reduce false barge-ins / echo cutting off speech.
- Inbound phone greeting is scheduled with `allow_interruptions=False` to reduce early echo/false barge-ins cutting off the first words.

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
- Realtime session config (auto response disabled): [`livekit_agent/openai_realtime_session.py`](../../livekit_agent/openai_realtime_session.py#L26-L38)
- Turn hook that triggers replies: [`OpenAIRealtimeAgent.on_user_turn_completed`](../../livekit_agent/openai_realtime_agent.py#L362-L458)

External references:
- LiveKit Agents “Pipeline nodes and hooks” (`on_user_turn_completed` note): https://docs.livekit.io/agents/logic/nodes/#on_user_turn_completed
- LiveKit Agents “Turn detection & interruptions”: https://docs.livekit.io/agents/logic/turns/
- LiveKit OpenAI Realtime plugin guide (turn detection options): https://docs.livekit.io/agents/models/realtime/plugins/openai/#turn-detection

## Contract: backend tools (v2)
- **URL:** `BACKEND_TOOLS_URL` (default ends with `/tools`)
- **Auth:** header `X-TOOLS-TOKEN` must equal env `TOOLS_TOKEN`
- **Response correlation:** results match by `tool_call_id`

See `docs/documentations/api-server.md` for the full `/tools` contract and failure semantics.

## Configuration (env vars)

### Required (default OpenAI Realtime path)
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `BACKEND_TOOLS_URL` (should end with `/tools`)
- `TOOLS_TOKEN` (shared secret for `X-TOOLS-TOKEN`)
- `OPENAI_API_KEY`

Optional:
- `OPENAI_REALTIME_VOICE` (passed to `openai.realtime.RealtimeModel(...)`)
- `AGENT_BACKEND_GUARDRAILS` (defaults to `true`; set to `false` to let the model manage the flow without calling `get_case_status` every turn)
- `SESSION_REPORTS_URL` + `SESSION_REPORTS_TOKEN` (optional: publish session reports at session end)

## Verification
- All tests: `./scripts/test_all.sh`
- Agent-only tests: `.venv/bin/python -m pytest -q livekit_agent/tests`

## Related docs
- `docs/specs/openai_realtime-spec.md`
- `docs/documentations/api-server.md`
- `docs/documentations/testing-and-evals.md`
- `docs/instructions/livekit-telephony-inbound-calls.md`
