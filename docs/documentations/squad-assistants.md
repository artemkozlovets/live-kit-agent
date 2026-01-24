# Squad Assistants (`squad/assistants/`)

> **Last Updated**: 2026-01-24  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `squad/assistants/*.json` + `*.prompt.md` defines the intended assistant flow and tool schemas.
- The LiveKit agent loads tool schemas from these JSON files to know which backend tools exist.
- The *actual* tool implementations live in the API server (`api_server/vapi/dispatcher.py` + handlers).

## Files
- `squad/assistants/customer_intake.json` + `squad/assistants/customer_intake.prompt.md`
- `squad/assistants/service_collection.json` + `squad/assistants/service_collection.prompt.md`
- `squad/assistants/booking.json` + `squad/assistants/booking.prompt.md`

## How schemas are used
- Tool schema loader: `livekit_agent/tools.py`
  - Reads `tools[]` entries where `type == "function"` and extracts `function.{name,description,parameters}`.
  - Adds local handoff tool schemas:
    - `handoff_to_CustomerIntake`
    - `handoff_to_ServiceCollection`
    - `handoff_to_Booking`

## Handoffs (Vapi vs LiveKit)
- In the API server (Vapi runtime), handoff tool names map to assistant IDs and set `destination` in the `/vapi/tools` response.
- In the LiveKit agent, these handoff tools are treated as local “phase change” actions (no backend call required).

## Gotchas (high-signal)
- Tool schemas in these JSON files should match backend expectations. If they drift:
  - the agent’s tool LLM may try to call tools that don’t exist, or
  - parameters may be ignored/mismatched.
- Some assistant JSONs include `call_id` as a tool parameter for `get_case_status`, but the backend derives call id from the payload (`message.call.id`).

## Related docs
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`
