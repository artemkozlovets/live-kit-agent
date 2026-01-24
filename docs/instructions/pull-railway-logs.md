# Pulling Railway Logs

Last updated: 2026-01-14

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

## Option 3: This repo's debug script (uses Railway GraphQL)
1. Set RAILWAY_API_TOKEN and RAILWAY_ENV_ID (environment UUID).
2. Optional: set RAILWAY_TOKEN_TYPE to match your token:
   - account (default)
   - team
   - project
3. Run: python -m squad.scripts.debug_call --railway-only --minutes 10
4. Auth check only: python -m squad.scripts.debug_call --railway-auth-check

If you're using a project token, the environment ID must match the token's scope.
You can fetch the correct environment ID with:

curl --request POST \
  --url https://backboard.railway.com/graphql/v2 \
  --header 'Project-Access-Token: <PROJECT_TOKEN>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"query { projectToken { projectId environmentId } }"}'

Notes:
- The script reads logs via squad/utils/railway_client.py.
- If you pass --call-id, it will narrow logs to that call’s time window (Railway logs often do not include the Vapi call ID).
