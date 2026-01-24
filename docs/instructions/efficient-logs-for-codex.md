# Efficient Logs for Codex (Low-Noise, Low-Tokens)

Last updated: 2026-01-14

## Big picture
Codex token usage is driven by how much text you paste into it. Log tooling (Vapi CLI, Railway CLI, or our scripts) does **not** cost tokens on its own — the cost happens when you copy/paste large outputs into Codex.

Your goal is to:
1) **pull the smallest useful view first**, and
2) only “zoom in” (artifact logs / JSON dumps) when you have a specific question.

## Rule of thumb: estimate “paste cost”
- Rough estimate: **1 token ≈ 4 bytes** of text.
- To estimate before pasting:
  - `YOUR_COMMAND | wc -c` → bytes
  - `YOUR_COMMAND | wc -c | awk '{print int($1/4)}'` → rough token estimate

## Lowest-noise defaults (recommended)

### 1) Vapi: get the latest call ID (tiny)
Use this when you just need the most recent call(s) without transcripts/artifacts.
```
VAPI_API_KEY=... python -m squad.scripts.fetch_call_logs --limit 1
```

### 2) Vapi: “debug one call” without artifact logs (small)
This prints call metadata + the correlation time window, but **does not** download the (very large) artifact logs.
```
VAPI_API_KEY=... python -m squad.scripts.debug_call --call-id <call-id> --vapi-only
```

### 3) Railway: smallest useful slice (usually best to paste)
Start here if you’re debugging server errors.
```
railway logs --lines 200 --filter "@level:error"
```

If you’re correlating tool calls, filter to the tool endpoint:
```
railway logs --lines 200 --filter "/vapi/tools"
```

### 4) Railway: correlate to a Vapi call by time window (small)
This uses the Vapi call timestamps to narrow Railway logs.
```
VAPI_API_KEY=... RAILWAY_API_TOKEN=... RAILWAY_ENV_ID=... \
python -m squad.scripts.debug_call --call-id <call-id> --railway-only
```

## When to “zoom in” (very noisy)

### Vapi artifact logs (huge)
Only enable this if you need deep pipeline details (tool call arguments, webhook deliveries, transcripts, etc.).
```
VAPI_API_KEY=... python -m squad.scripts.debug_call --call-id <call-id> --vapi-only --include-artifact-logs
```

Avoid pasting artifact logs directly into Codex. Instead:
- filter locally first (e.g., grep for a tool name / error code), then paste 20–50 lines.

### JSON modes (larger output)
`--json` and `--raw` are great for saving to a file, but they’re usually expensive to paste.
Prefer the default human-readable output unless you know you need structured parsing.

If you use `--json`, prefer writing to a file so you don’t spam your terminal (and then accidentally paste it):
```
VAPI_API_KEY=... RAILWAY_API_TOKEN=... RAILWAY_ENV_ID=... \
python -m squad.scripts.debug_call --call-id <call-id> --json --output /tmp/debug_call.json
```

## What to paste into Codex (minimal set)
If you want help debugging, paste:
- Call ID
- `createdAt` / `endedAt` (or the time window from `debug_call`)
- `endedReason` (and any error code)
- The **smallest** set of relevant Railway lines (ideally only errors or `/vapi/tools`)
- If it’s a tool issue: the tool name + the arguments (don’t paste entire transcripts)
