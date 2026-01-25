# LiveKit Agent (Codex Context)

> **Last Updated**: 2026-01-25  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `livekit_agent/` runs a LiveKit Agents worker that **delegates decisions** to the backend tools server (`BACKEND_TOOLS_URL`).
- Preflight must complete (callback phone → `validate_phone` → `check_customer`) before the agent will call `get_case_status`.
- Main loop: call `get_case_status(last_user_message=...)` every user turn, then follow:
  - `response_mode` ordering
  - `immediate_message` (speech)
  - `then_action` (tool calls)

## Entry points / key files
- Agent worker + LiveKit server setup: [`livekit_agent/agent.py`](../../livekit_agent/agent.py)
- Deterministic state machine + response ordering: [`livekit_agent/flow_controller.py`](../../livekit_agent/flow_controller.py)
- Backend HTTP + response parsing: [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py)
- Vapi-shaped request payload builder: [`livekit_agent/vapi_payload.py`](../../livekit_agent/vapi_payload.py)
- Tool schema loader (from `squad/assistants/*.json`): [`livekit_agent/tools.py`](../../livekit_agent/tools.py)
- Offline eval harness: [`livekit_agent/evals/`](../../livekit_agent/evals)

## Core loop (what happens on each turn)
- **on_enter:** try to detect SIP phone number and start preflight. (`livekit_agent/agent.py`)
- **Preflight:** collect callback number → call backend tools:
  - `validate_phone(phone_number=...)`
  - `check_customer(phone_number=...)`
- **Business turn:** call `get_case_status(last_user_message=user_text)` and execute planned actions.

## Contracts

### Tool call request (agent → backend)
Built by `build_vapi_tool_call_request(...)`:
- File: [`livekit_agent/vapi_payload.py`](../../livekit_agent/vapi_payload.py)
- Payload shape (high-level):
  - `message.type = "tool-calls"`
  - `message.call.id = <call_id>`
  - `message.call.customer.number = <confirmed_callback_number>` (only when known)
  - `message.customer.number = <sip_phone_number | None>`
  - `message.toolCallList = [{id, function:{name, arguments:<json string>}}]`

### Tool call response (backend → agent)
Parsed by `BackendToolsClient.call_tool(...)`:
- File: [`livekit_agent/backend_tools_client.py`](../../livekit_agent/backend_tools_client.py)
- Required:
  - top-level `results: list`
  - an entry matching `toolCallId == <tool_call_id>`
  - `result` is either:
    - a dict (returned as-is), or
    - a JSON string that parses to a dict

### `then_action` execution
The agent treats `then_action` as an *instruction string* that must be converted into tool calls.

Two modes:
- **With tool LLM** (`GOOGLE_API_KEY` set): stream tool calls and merge partial JSON args; ignore unknown tool names; fall back if none parsed.
  - Tool LLM is only for *parsing instructions*, not for deciding what to do.
  - The tool list excludes `get_case_status` (agent calls that deterministically).
- **Without tool LLM:** regex fallback that extracts patterns like `Call add_service`.

## Configuration (env vars)

### Required for real voice runs
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `DEEPGRAM_API_KEY` (STT)
- `DEEPGRAM_EAGER_EOT_THRESHOLD` (optional; must be a float in **0.3–0.9** or Deepgram can reject STT startup)
- `BACKEND_TOOLS_URL` (defaults to a dev URL in `livekit_agent/agent.py`)
  - Railway base: `https://call-agent-development.up.railway.app/`
  - Set: `https://call-agent-development.up.railway.app/vapi/tools`

### Optional providers
- `CARTESIA_API_KEY` (TTS)
- `GOOGLE_API_KEY` + `GOOGLE_LLM_MODEL` (tool LLM for parsing `then_action`)

### Behavior / runtime
- `LIVEKIT_AGENT_NAME` (dispatch filter)
- `LOG_LEVEL`, `LOG_PII`
- `SKIP_CALLBACK_PREFLIGHT` (bypass preflight only when no SIP number; sets callback to `"web"`)
- Worker ports: `HOST`, `PORT`, `PROMETHEUS_PORT`, `PROMETHEUS_MULTIPROC_DIR`

## Invariants / gotchas
- **Preflight gate:** `FlowController.can_call_get_case_status` stays false until:
  - a callback number is normalized/accepted, and
  - customer check completes.
- **Backend failure mode:** on backend errors, the agent speaks a single “trouble connecting” message and stops processing future turns.
- **SIP phone detection:** agent reads SIP participant attributes (`sip.phoneNumber`) or identity formatted like `+1555...`.
- **“Silent agent” gotcha:** if Deepgram STT fails at startup (for example, invalid `DEEPGRAM_EAGER_EOT_THRESHOLD`), the session can close before any response. The agent parses/clamps this value here: [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L482).

## Debugging (production / LiveKit Cloud)
- Tail agent logs: `lk agent logs --log-type deploy`
- Agent emits extra error/close context:
  - `AgentSession error`: [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L540)
  - `AgentSession closing`: [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L582)

## Tests / evals
- Default tests: `pytest.ini` targets `livekit_agent/tests`.
- Offline eval suite (no network): `python -m livekit_agent.evals` (scenarios in `livekit_agent/evals/scenarios.py`).
