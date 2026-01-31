# LiveKit Telephony Inbound Calls (Codex Context)

> **Last Updated**: 2026-01-30  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** inbound PSTN calls to a LiveKit Phone Number should create a room, auto-dispatch our agent, and the agent should greet immediately using caller ID DB lookup.
- **Entry points:** LiveKit Cloud → Telephony (Phone Numbers + Dispatch rules); agent runtime: [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L203), greeting: [`livekit_agent/openai_realtime_agent.py`](../../livekit_agent/openai_realtime_agent.py#L184), caller lookup: [`api_server/vapi/handlers/case_status.py`](../../api_server/vapi/handlers/case_status.py#L246).
- **Where to change:** dispatch rule JSON (`roomConfig.agents`), caller-ID extraction, and the “speak first” timing for `on_enter`.
- **How to verify:** `lk number get …` + `lk sip dispatch list` + place a real call + `lk room list` + `lk room participants list <room>` + `lk agent logs --log-type deploy`.

## Big picture
Inbound telephony to an agent is a routing + media chain:

1. Caller dials a **LiveKit Phone Number** (inbound only).
2. LiveKit SIP matches a **SIP dispatch rule** and creates a **SIP participant** in a LiveKit room.
3. The dispatch rule can include `roomConfig.agents` to **dispatch the agent** into the same room.
4. The caller will keep hearing a dial tone until **another participant publishes tracks** (agent audio). If the agent never publishes audio, the call “feels unanswered”.

External references (LiveKit docs):
- Phone numbers are inbound-only (as of now): https://docs.livekit.io/telephony/start/phone-numbers/
- LiveKit Phone Numbers do not support call transfers via `TransferSipParticipant` yet: https://docs.livekit.io/telephony/start/phone-numbers/#considerations
- Inbound call workflow + “dial tone until tracks published”: https://docs.livekit.io/telephony/accepting-calls/workflow-setup/
- Dispatch rule + `roomConfig.agents`: https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/

## Setup / verify routing (CLI-first)

### 0) Get the agent name (LiveKit agent ID)
This repo’s LiveKit Cloud agent id is the value in `livekit.toml`:
```bash
cat livekit.toml
```

### 1) List dispatch rules + phone numbers
```bash
lk sip dispatch list
lk number list
```

### 2) Ensure your dispatch rule explicitly dispatches the agent
LiveKit recommends explicit agent dispatch for inbound SIP calls using `roomConfig.agents`. (LiveKit docs: https://docs.livekit.io/agents/server/agent-dispatch/#dispatch-from-inbound-sip-calls)

Minimal JSON shape (paste in LiveKit Cloud “JSON editor” or use `lk sip dispatch create/update` with a JSON file):
```json
{
  "dispatch_rule": {
    "name": "inbound-calls",
    "rule": { "dispatchRuleIndividual": { "roomPrefix": "call-" } },
    "roomConfig": { "agents": [{ "agentName": "CA_..." }] }
  }
}
```

Gotcha: LiveKit allows multiple dispatch rules per trunk, but (per LiveKit docs) they must use different pins if associated with the same trunk. If you omit `trunk_ids` / pin, you can accidentally create an overlapping “match all” rule. (LiveKit docs: https://docs.livekit.io/telephony/#dispatch-rules)

### 3) Assign the phone number to the dispatch rule
```bash
lk number update --id <PHONE_NUMBER_ID> --sip-dispatch-rule-id <DISPATCH_RULE_ID>
```

## How caller ID reaches our database (repo-specific)

### 1) Caller ID extraction (agent runtime)
We attempt to read the caller phone number from the SIP participant:
- `sip.phoneNumber` participant attribute (preferred)
- otherwise parse the participant identity (some projects use `sip_+1...`)

See:
- [`livekit_agent/agent.py` `_extract_sip_phone_number`](../../livekit_agent/agent.py#L158-L179)
- [`livekit_agent/openai_realtime_agent.py` `_refresh_sip_phone_number_from_room`](../../livekit_agent/openai_realtime_agent.py#L148-L183)

### 2) Tools v2 payload: raw caller ID vs confirmed callback number
The agent sends the raw caller ID as top-level `customer.number`, and only sends a confirmed callback as `call.customer.number`.

See:
- [`livekit_agent/tools_v2_payload.py` `build_tools_v2_request`](../../livekit_agent/tools_v2_payload.py#L6-L59)

### 3) Backend lookup
`get_case_status` uses the caller phone number for a DB lookup when the session doesn’t already have a `customer_id`.

See:
- [`api_server/vapi/handlers/case_status.py` `_get_caller_phone_number`](../../api_server/vapi/handlers/case_status.py#L246-L262)

### 4) Speak-first greeting (inbound SIP)
On session start, `OpenAIRealtimeAgent.on_enter()` tries to:
1) determine caller phone number,
2) call `get_case_status(last_user_message=" ")` to fetch `customer.first_name`, then
3) generate a greeting like:
“Hello <first_name>, this is Sarah from AFS. I have your number as <caller_phone>. Is this still the best number to reach you?”

See:
- [`livekit_agent/openai_realtime_agent.py` `_build_phone_greeting`](../../livekit_agent/openai_realtime_agent.py#L128-L146)
- [`livekit_agent/openai_realtime_agent.py` `on_enter`](../../livekit_agent/openai_realtime_agent.py#L184-L250)

## Critical gotcha: “agent doesn’t speak first” on inbound calls
If the caller keeps hearing dial tone / silence, the agent may be in the room but **audio output isn’t ready yet** when `on_enter()` runs.

Why this matters:
- For SIP inbound, LiveKit’s workflow explicitly notes the caller continues hearing dial tone until another participant publishes tracks. (LiveKit docs: https://docs.livekit.io/telephony/accepting-calls/workflow-setup/)
- In `livekit-agents`, `on_enter` runs asynchronously during `session.start(...)` (it is not awaited), so it can fire before the Room audio output track is subscribed/published and/or before the SIP participant is linked.

**Fix pattern (conceptual):**
- Delay the first `generate_reply(...)` until:
  - a SIP participant exists in `room.remote_participants`, and
  - the room audio output is subscribed/published (RoomIO subscribed future is done).
- Alternative: trigger greeting on `room.on("participant_connected", ...)` when the SIP participant joins, and only greet once.

## Common gotcha: “two agents talking” / interruptions on speakerphone (mobile)
If an inbound call sounds like the agent is **talking to itself**, interrupting constantly, or the flow feels choppy:

**Likely cause:** you're using **speakerphone** and the phone's mic is picking up the agent's own audio (echo/feedback). With OpenAI Realtime + VAD/barge-in, that echo is treated like new user speech and can cancel/interrupt the agent mid-sentence.

**What this looks like:**
- The greeting gets cut off (so you might not hear the "I have your number as ..." line).
- It can feel like "two agents" because the agent keeps reacting to its own audio.

**Fix (recommended):**
- Turn off speakerphone; use the handset earpiece or headphones.
- Lower volume and keep the mic away from the speaker if you must go hands-free.

## Verification (what to run + what “good” looks like)

### Happy path: routing + join
1) Place a real call to the LiveKit phone number.
2) Find the room that was created:
```bash
lk room list
```
3) Inspect participants (expect a SIP participant + an agent participant):
```bash
lk room participants list <ROOM_NAME>
```

### Happy path: agent is alive + logs show work
```bash
lk agent status
lk agent logs --log-type deploy
```

Expected signals:
- `lk room participants list` shows a SIP participant (often identity like `sip_+1...`) and an `agent-...` participant.
- LiveKit agent logs include “starting agent session” from [`livekit_agent/agent.py`](../../livekit_agent/agent.py#L214).
- Railway logs show `POST /tools` during the call (see `docs/instructions/verify-railway-livekit-sync.md`).

### Failure case: call rings / dial tone never ends
Most common causes:
- Phone number not assigned to the intended dispatch rule.
- Dispatch rule doesn’t include `roomConfig.agents` (SIP participant joins, agent never does).
- Agent starts but fails before publishing audio (missing `OPENAI_API_KEY`, plugin missing, backend `/tools` returning `401`, etc.).
- Speak-first greeting fires too early (audio output not ready).

Start here:
- [`docs/instructions/debug-livekit-agent-silence.md`](debug-livekit-agent-silence.md)
- [`docs/instructions/verify-railway-livekit-sync.md`](verify-railway-livekit-sync.md)

## Related docs (repo)
- [`docs/documentations/livekit-agent.md`](../documentations/livekit-agent.md)
- [`docs/documentations/api-server.md`](../documentations/api-server.md)
- [`docs/specs/openai_realtime-spec.md`](../specs/openai_realtime-spec.md)
- [`docs/instructions/debug-livekit-agent-silence.md`](debug-livekit-agent-silence.md)
- [`docs/instructions/verify-railway-livekit-sync.md`](verify-railway-livekit-sync.md)
