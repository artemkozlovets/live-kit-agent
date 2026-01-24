# Vapi Export Snapshots (`vapi_export/`)

> **Last Updated**: 2026-01-24  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- `vapi_export/` is **historical reference**, not source of truth.
- Use it only to compare older Vapi configuration vs current repo behavior (`squad/assistants/` + `api_server/` + `livekit_agent/`).

## What’s in here
- `vapi_export/phones/` — exported phone config(s).  
  Example: [`vapi_export/phones/phone_c09ef242.json`](../../vapi_export/phones/phone_c09ef242.json)
- `vapi_export/tools/` — exported tool definitions (IDs, parameters, server URL).  
  Example: [`vapi_export/tools/tool_95968022-2d9c-4eea-a335-c67258a43147.json`](../../vapi_export/tools/tool_95968022-2d9c-4eea-a335-c67258a43147.json)
- `vapi_export/workflows/` — exported workflow graph(s).  
  Example: [`vapi_export/workflows/workflow_4ebe74ed.json`](../../vapi_export/workflows/workflow_4ebe74ed.json)

## Important gotcha: parameters may differ from current code
For example, the exported `get_case_status` tool may use a parameter name like `user_message`, while the current code expects `last_user_message`:
- Current tool expects `last_user_message`: [`api_server/vapi/handlers/case_status.py:252-257`](../../api_server/vapi/handlers/case_status.py#L252-L257)

Treat exports as “historical snapshots” and rely on `squad/assistants/*.json` + the actual backend code for current behavior.

## Related docs
- [`docs/documentations/squad-assistants.md`](./squad-assistants.md)
- [`docs/documentations/api-server.md`](./api-server.md)
