# Realtime Human Transfer (Codex Context)

> **Last Updated**: 2026-01-31  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** let the Realtime voice agent offer a **cold transfer** to a human agent, then transfer only after the caller confirms.
- **Transfer target:** default `tel:+13053179840` (override with `HUMAN_TRANSFER_TO`).
- **How it works:** the model calls a local tool `transfer_to_human` which uses the LiveKit SIP API to transfer the active SIP participant.
- **Important limitation:** LiveKit **Phone Numbers** (inbound-only) do **not** support transfers via `TransferSipParticipant` yet; for real transfers you need a SIP trunk provider (ex: Twilio) with SIP REFER/PSTN transfer enabled.
- **How to verify:** `python -m pytest -q -p no:cacheprovider livekit_agent/tests/test_openai_realtime_agent_transfer_to_human_local.py`.
- **How to debug (production):** fetch the session report for the call and look for a `function_tools_executed` event where `name=="transfer_to_human"`; if the output error code is `transfer_not_supported`, this is the LiveKit Phone Numbers limitation (not a prompt bug).

## Big picture
In a phone call, after the agent greets you, something has to detect **“you finished talking”** (turn detection) and then trigger the next AI reply.

Separately, when the caller is **frustrated** (or asks for a human), the agent should:
1. Ask: “Would you like to connect to a human agent?”
2. If the caller confirms (LLM judgment; not deterministic string-matching), perform a SIP transfer.

## Key files
- Tool schema registration: [`livekit_agent/tools.py`](../../livekit_agent/tools.py#L1)
- Local tool implementation + prompt rules: [`livekit_agent/openai_realtime_agent.py`](../../livekit_agent/openai_realtime_agent.py#L1)

## Flow (happy path)
1. Caller expresses frustration or asks for a human.
2. Agent offers a **cold transfer**: “Would you like to connect to a human agent?”
3. If the caller confirms, the model calls tool `transfer_to_human`.
4. The agent transfers the active SIP participant using `TransferSIPParticipantRequest`.

## Contracts / invariants
- **Consent required:** do not transfer until the caller clearly confirms.
- **Non-deterministic confirmation:** do not hardcode keyword lists in code; use LLM judgment.
- **Transfer address format:** use a SIP/TEL transfer target like `tel:+13053179840` or `sip:agent@example.com`.
- **Telephony-only:** transfer only works if a SIP participant exists in the room.

## Configuration
- `HUMAN_TRANSFER_TO` — defaults to `tel:+13053179840`
  - Accepts: `tel:+E164` or `sip:...`
  - Convenience: bare phone numbers (e.g. `305-317-9840`) are normalized to `tel:+...` (punctuation stripped)
- LiveKit API creds (required for transfer calls):
  - `LIVEKIT_URL`
  - `LIVEKIT_API_KEY`
  - `LIVEKIT_API_SECRET`

## Verification
- Happy path (unit): `python -m pytest -q -p no:cacheprovider livekit_agent/tests/test_openai_realtime_agent_transfer_to_human_local.py`
- Integration (manual, LiveKit CLI): `lk sip participant transfer --to "tel:+13053179840" --room "<room>" --identity "<sip-participant-identity>"`
- Smoke (LiveKit Cloud, no browser): `./scripts/run_livekit_cloud_smoke.sh --scenario transfer`
  - Expected today (CLI-only room): `no_sip_participant` (proves the model attempts the transfer tool call when the user is frustrated + confirms).
  - Real phone-call behavior depends on your telephony setup (LiveKit Phone Numbers currently → `transfer_not_supported`).

## Failure modes / gotchas
- **Tool call succeeds but nothing happens** → transfer target isn’t reachable / wrong `tel:` address → verify `HUMAN_TRANSFER_TO`.
- **Tool fails with `invalid_transfer_target`** → `HUMAN_TRANSFER_TO` is misconfigured → set it to `tel:+...` or `sip:...` and redeploy/restart the agent.
- **Tool fails with `transfer_not_supported`** → you're using LiveKit Phone Numbers → transfers aren’t supported yet; switch to a SIP trunk provider to enable call forwarding.
- **Tool returns `no_room`** → agent isn’t attached to a LiveKit room (console/tests) → transfers only apply to telephony rooms.
- **Tool returns `no_sip_participant`** → not a phone call (Meet/web participant only) → transfer only applies to SIP participants.
- **Tool returns `transfer_failed`** → LiveKit API creds missing/invalid (`LIVEKIT_*`) or SIP transfer not enabled for that project.

### Debugging from a session report (fast, no UI)
If the caller reports “technical issues” when transferring, verify what actually happened:
```bash
./scripts/fetch_session_reports.py --url "$SESSION_REPORTS_URL" --room "<ROOM_NAME>" --raw
```

Look for an event like:
- `type == "function_tools_executed"`
- `function_call_outputs[].name == "transfer_to_human"`

Common result:
- `{"ok": false, "error": {"code": "transfer_not_supported", ...}}` → LiveKit Phone Numbers do not support transfers yet.

## Related docs
- [`docs/documentations/livekit-agent.md`](./livekit-agent.md)
- [`docs/documentations/debug.md`](./debug.md)
- [`docs/instructions/debug-meet-call-stuck.md`](../instructions/debug-meet-call-stuck.md)
