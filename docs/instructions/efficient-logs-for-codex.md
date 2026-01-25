# Efficient Logs for Codex (Low-Noise, Low-Tokens)

Last updated: 2026-01-25

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

### 1) LiveKit Cloud: agent status (tiny)
```
lk agent status
```

### 2) LiveKit Cloud: tail agent logs (small → medium)
```
lk agent logs --log-type deploy
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

Tip: add timestamps for correlation:
```
railway logs --lines 200 --filter "@level:error" --json
railway logs --lines 200 --filter "/vapi/tools" --json
```

## When to “zoom in” (very noisy)

### JSON log mode (larger output)
Prefer `--json` only when you need timestamps/correlation.
If you do use `--json`, consider saving to a file:
```
railway logs --lines 500 --filter "@level:error" --json > /tmp/railway_errors.jsonl
```

## What to paste into Codex (minimal set)
If you want help debugging, paste:
- LiveKit room name (if known) + approximate UTC timestamp
- `lk agent status` (IDs + version only)
- The **smallest** relevant slice of `lk agent logs` (errors/warnings only)
- The **smallest** relevant slice of Railway logs (ideally only errors or `/vapi/tools`)
