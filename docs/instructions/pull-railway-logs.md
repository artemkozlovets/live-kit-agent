# Pulling Railway Logs

Last updated: 2026-01-25

## Big picture
Railway logs show what your service printed during builds and runtime. Use them to debug failures or confirm behavior.

## If you’re pasting into Codex (token-saving)
Prefer short, filtered output. See: `docs/instructions/efficient-logs-for-codex.md`.

## Option 1: Railway dashboard (quick, visual)
1. Open the project in Railway.
2. Click Observability > Log Explorer.
3. Use the filter box or time range to narrow results.

## Option 2: Railway CLI (quick, terminal)
1. Install the Railway CLI and authenticate (railway login) or set a token:
   - Project token → set RAILWAY_TOKEN
   - Account/Team token → set RAILWAY_API_TOKEN
2. Run railway logs to stream the most recent deployment logs.

Lowest-noise starting points:
```
# Show only error-level lines (smallest)
railway logs --lines 200 --filter "@level:error"

# Focus on tool calls to our server
railway logs --lines 200 --filter "/vapi/tools"
```

## Tip: include timestamps (best for correlating to a specific call)
Use `--json` so each log line includes a `timestamp` you can line up with LiveKit agent logs.

```bash
railway logs --lines 200 --filter "@level:error" --json
railway logs --lines 200 --filter "/vapi/tools" --json
```

## Related docs
- `docs/instructions/verify-railway-livekit-sync.md`
- `docs/instructions/debug-livekit-agent-silence.md`
