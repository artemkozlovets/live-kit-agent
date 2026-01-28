# LiveKit Agent (Codex Context)

> **Last Updated**: 2026-01-28  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `livekit_agent/` runs the LiveKit Agents worker.
- **Default conversation engine:** OpenAI Realtime (`AGENT_ENGINE=openai_realtime`).
- **Backend tools contract:** agent calls `POST /tools` (v2) with auth header `X-TOOLS-TOKEN` (env `TOOLS_TOKEN`).
- **Rollback lever:** `AGENT_ENGINE=legacy` uses the previous Deepgram+Cartesia pipeline.
- **How to verify:** `./scripts/test_all.sh`

## Key files (start here)
- Worker entrypoint + engine selection: `livekit_agent/agent.py`
- OpenAI Realtime agent logic (backend-first turn hook + tool forwarding): `livekit_agent/openai_realtime_agent.py`
- OpenAI Realtime session factory (plugin import is lazy): `livekit_agent/openai_realtime_session.py`
- Backend HTTP client + v2 result parsing: `livekit_agent/backend_tools_client.py`
- Tools v2 payload builder: `livekit_agent/tools_v2_payload.py`
- Deterministic flow controller (legacy pipeline): `livekit_agent/flow_controller.py`
- Offline eval harness (no network): `livekit_agent/evals/`

## Runtime flow (happy path)
1. LiveKit starts the agent worker (`python -m livekit_agent.agent ...`).
2. `livekit_agent/agent.py` reads `AGENT_ENGINE`:
   - `openai_realtime` (default): builds an OpenAI Realtime `AgentSession` and starts `OpenAIRealtimeAgent`.
   - `legacy`: starts the previous Deepgram STT + Cartesia TTS pipeline with `VapiAdapterAgent`.
3. During conversation:
   - Agent calls backend `get_case_status(last_user_message=...)` on each user turn.
   - Tool calls are forwarded to the backend via `BackendToolsClient.call_tool(...)`.

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
- `AGENT_ENGINE` (defaults to `openai_realtime`; set to `legacy` to roll back)

### Legacy-only (Deepgram+Cartesia path)
These are only required when `AGENT_ENGINE=legacy`:
- `DEEPGRAM_API_KEY` (+ optional `DEEPGRAM_STT_MODEL`, `DEEPGRAM_EAGER_EOT_THRESHOLD`)
- `CARTESIA_API_KEY` (+ optional `CARTESIA_TTS_MODEL`, `CARTESIA_VOICE_ID`, `CARTESIA_SPEED`, `CARTESIA_TEXT_PACING`)
- `GOOGLE_API_KEY` (optional: tool-LLM parsing for `then_action`)

## Verification
- All tests: `./scripts/test_all.sh`
- Agent-only tests: `.venv/bin/python -m pytest -q livekit_agent/tests`

## Related docs
- `docs/specs/openai_realtime-spec.md`
- `docs/openai_realtime-tdd-plan.md`
- `docs/documentations/api-server.md`
- `docs/documentations/testing-and-evals.md`
