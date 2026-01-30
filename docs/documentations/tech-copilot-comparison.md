# Tech Copilot Comparison (and how to mirror the pattern)

> **Last Updated**: 2026-01-30  
> **Audience**: repo maintainers + future Codex work  
> **Status**: Draft

## Big picture
Tech Copilot and this repo both run an **OpenAI Realtime “main agent”** + a **“sub-agent”** that does heavier work. The difference is *where* that heavier work runs and *when* it happens:

- **Tech Copilot**: a Primer Sub-Agent **pre-computes** context and persists it to DB, so the realtime session can start “already primed”.
- **livekit-proj (this repo)**: historically we computed guidance via `get_case_status` **on every turn** (backend-first). We now also support **OpenAI-first** mode, and we can add a Primer-like async job to avoid per-turn backend latency.

---

## Tech Copilot (reference architecture)

### Components (what exists in Tech Copilot)
- **Realtime session host**: a FastAPI WebSocket server that owns the OpenAI Realtime session lifecycle.
- **Main agent**: OpenAI Realtime agent that speaks with the user and calls tools.
- **Tools + DB**: tool code runs in-process and can read/write DB directly.
- **Primer Sub-Agent**: runs before (or on-demand during) the live session and writes *prepared context* artifacts to DB.

### Typical flow (pre-prime, then connect)
```
(earlier) Primer Sub-Agent
   -> reads DB / external data
   -> generates prepared_context (and other artifacts)
   -> writes to DB

(later) User connects to realtime
   -> WebSocket server fetches prepared_context from DB
   -> creates OpenAI Realtime session with that context
   -> agent runs fast; tools handle persistence/validation
```

### Key idea
**Do expensive work once** (primer) and **reuse it** during realtime turns.

---

## livekit-proj (this repo) today

### Components
- **Realtime transport**: LiveKit rooms + LiveKit Cloud dispatch (agent joins the room).
- **Main agent**: `livekit_agent/openai_realtime_agent.py` runs inside a LiveKit worker.
- **Tools backend**: `api_server/` exposes `POST /tools` (v2) and owns DB + policy/guardrails.

### Two “brain modes” (important recent change)
1) **Backend-first (default)**: call `get_case_status` each user turn, inject it into context, then let OpenAI respond.
2) **OpenAI-first**: skip the per-turn `get_case_status` preflight and let OpenAI drive the conversation, calling tools only when needed.

This is controlled by:
- `AGENT_BACKEND_GUARDRAILS=true|false` (see `livekit_agent/agent.py` and `livekit_agent/openai_realtime_agent.py`)

---

## Are we proposing the same scheme as Tech Copilot?
Yes — **Option B (async primer job + polling)** is the same architectural pattern:

> Primer produces a persisted “prepared context artifact” off the realtime path; main realtime session consumes it later.

The main difference is **timing**:
- **Tech Copilot** often primes *before* the session starts (so no polling is needed).
- **Option B here** primes *after* the LiveKit session starts, so the agent may need to poll and inject the context once it’s ready.

If we want to be even closer to Tech Copilot, we can trigger priming earlier (for example, when we first know the caller phone number / call_id), so the context is ready by the time the first real user turn arrives.

---

## How to mirror Tech Copilot’s “Primer + main agent” pattern in this repo (Option B)

### Proposed backend tools
Add two backend tools (names are placeholders; the important part is the contract):
- `prime_call_context(call_id, customer, assistant, ...) -> { job_id, status }`
  - starts a background job to compute prepared context and store it
  - returns immediately (fire-and-forget)
- `get_call_context(call_id) -> { status, prepared_context? }`
  - returns `ready` + the prepared context when finished

### Where the Primer should run (recommended)
Run it in the **tools backend** (`api_server/`), because that’s where:
- the DB connection exists,
- the tool/policy boundary already exists, and
- we can keep the LiveKit worker light and reliable.

### Data storage: session_store vs Postgres (design decision)
To match Tech Copilot’s reliability, store primer outputs in **Postgres** (durable).

If we store primer output only in `session_store` (in-memory), we risk losing it on restarts/redeploys.

### Agent behavior (OpenAI-first + inject once)
In LiveKit worker:
1) Start the call in **OpenAI-first** mode (`AGENT_BACKEND_GUARDRAILS=false`).
2) At session start (or after first user turn):
   - call `prime_call_context` (don’t wait)
3) On next turns (or on a timer):
   - call `get_call_context`
   - when `ready`, inject `prepared_context` as a system message once

### Sequence diagram
```
LiveKit session start
  -> Agent: prime_call_context (async)
  -> Agent: continues conversation normally (OpenAI-first)

Later
  -> Agent: get_call_context
  -> if ready: inject prepared_context once
  -> continue (tools used only when needed)
```

---

## Key differences that will remain (even after Option B)

### Transport boundary
- **Tech Copilot**: WebSocket server owns the OpenAI session directly.
- **This repo**: LiveKit owns the room/media; our agent worker joins as a participant.

### Tool execution boundary
- **Tech Copilot**: tools are in-process (direct DB access).
- **This repo**: tools are remote (`POST /tools`) so auth, latency, and failure modes matter more.

### Policy boundary (important)
This repo’s backend enforces safety rules (ex: booking confirmation). That should remain even with OpenAI-first + primer. The Primer should help the model, but not become a bypass for backend policy.

---

## Open questions (to decide before implementing)
1) **When to prime?**
   - on agent join, after first user text, or only after confirmed callback number?
2) **What is the “prepared context” format?**
   - plain string, structured JSON, or both?
3) **Durability + lifecycle**
   - Postgres table keyed by `call_id` with TTL? How do we clean up?
4) **Observability**
   - measure: time-to-ready, % calls with context ready before 2nd turn, and how often tool latency causes “stuck”.

