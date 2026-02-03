# Vehicle ID + Make/Model policy

## Big picture
Two competing realities in voice calls:
- Callers often identify a vehicle by a **nickname** (“Big Pete”), which is convenient but ambiguous.
- For unit matching and sane record keeping, we still want a more precise identifier:
  - **VIN** (best), or at least
  - **make + model** (acceptable fallback).

This doc captures the repo’s policy for asking once (without nagging) and persisting what the caller provides.

## Policy (desired behavior)
1) **Ask at least once** for VIN or make/model when the call only has a nickname:
   - When `unit_nickname` is the only vehicle ID and we already have `service_location` + `service_complaint`,
   - the backend guidance (`get_case_status`) prompts:
     - “Do you have the VIN for that vehicle? If not, what’s the make and model (for example, Ford F‑150)?”
2) **One-time prompt**:
   - If the caller doesn’t answer, continue the flow (do not repeatedly ask).
   - If VIN fallback is already triggered (`vin_attempts >= 3`), do not nag for VIN/make-model again.
3) **Persist what the caller says**:
   - If the caller provides make/model, store it in session on the current service as:
     - `vehicle_make`
     - `vehicle_model`
   - When a unit must be **auto-created** during `store_service_order`, pass make/model through so the created DB unit record uses those values instead of `"Unknown"`.

## Where it’s implemented
- Prompting (one-time):
  - `api_server/vapi/handlers/case_status.py` sets `session["vin_or_make_model_prompted"]=True` and returns `response_mode="speak_first"` for the one-time question.
- Persistence to the DB (auto-create path):
  - `api_server/vapi/handlers/order.py` passes `vehicle_make`/`vehicle_model` into unit resolution/creation.
  - `api_server/vapi/unit_resolution.py` uses provided make/model when building `StoreUnitArgs` (fallbacks remain `"Unknown"`).
- Tool contracts (what the model can send):
  - `squad/assistants/service_collection.json`
    - `add_service` supports optional `vehicle_make` / `vehicle_model`
    - `update_service_order.updates` supports optional `vehicle_make` / `vehicle_model`
- Agent guidance:
  - `livekit_agent/openai_realtime_agent.py` instructs the model to save `vehicle_make`/`vehicle_model` when the caller provides them.

## How to validate (local)
Targeted tests:
- Prompting behavior:
  - `.venv/bin/python -m pytest -q api_server/tests/test_get_case_status_vehicle_identifier_prompt.py`
- Make/model stored on auto-created units:
  - `.venv/bin/python -m pytest -q api_server/tests/test_vapi_adapter_step_7_store_service_order.py -k make_model`
  - `.venv/bin/python -m pytest -q api_server/tests/test_vapi_adapter_unit_auto_create.py -k make_model`
- Tool schema includes the fields:
  - `.venv/bin/python -m pytest -q livekit_agent/tests/test_service_schema_includes_vehicle_make_model.py`

Full suite:
- `./scripts/test_all.sh`

## Known limitation
This repo currently persists make/model to the database **only** when the unit is auto-created (unit not found).
If an existing unit is resolved (by VIN/unit_number/nickname), there is no unit-update tool in this repo to backfill make/model.
