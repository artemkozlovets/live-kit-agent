# Repetition policy (reduce mid-call recaps)

## Goal
Avoid “echo-y” conversations where the agent repeatedly reads back the caller’s details (name, email, address, etc.) during slot-filling.

Desired behavior in this repo:
- **Pre-booking** (`customer_intake`, `service_collection`): acknowledge briefly and ask for what’s missing.
- **Booking** (`booking`): give **one** concise recap (**service + location + vehicle only**), then ask for an explicit **yes/no** before booking.
- **Post-confirmation** (after a clear “yes”): **do not recap again**. Call `confirm_services`, then proceed to `store_service_order` and finish the call.

This aligns with the repo’s slot-filling guardrail flow: **info dump → fill session → ask only missing → confirm at end → book**.

## Where it’s implemented
- Runtime prompt + per-turn policy injection: `livekit_agent/openai_realtime_agent.py`
  - The backend-first loop calls `get_case_status` every user turn.
  - We use `case_status.current_phase` to inject a short “recap policy” instruction per turn.
  - Extra guard: when `case_status.booking.status == "confirmed"` or the user is responding to the confirmation prompt (`message_category` is `confirmation`/`decline`), we inject a **no-recap** instruction so the model doesn’t repeat the recap during `store_service_order`.

## Why per-turn instructions (vs a static prompt)
The agent is intentionally phaseful (backend-owned session state). Per-turn instructions allow us to:
- keep slot-filling terse while the caller is still providing info, and
- enable the single recap once we reach booking.

OpenAI Realtime also supports updating session instructions dynamically (`session.update`), which is another option for phase-based prompting. In this repo, we currently rely on per-turn instructions injected at `session.generate_reply(...)` time.

## How to validate (local)
- Unit tests: `.venv/bin/python -m pytest -q`
- Voice smoke (no mic): `./scripts/run_openai_realtime_audio_smoke.sh --turn "..." --modalities "text,audio"`

Targeted regression coverage:
- `livekit_agent/tests/test_openai_realtime_agent_recap_policy_instructions.py`
- `livekit_agent/tests/test_openai_realtime_agent_recap_policy_instructions_post_confirmation.py`
