# Railway CLI

Last updated: 2026-01-14

## Big picture
The Railway CLI lets you manage projects, deployments, and logs from the terminal. Use it for quick log checks, linking a repo to a project, and environment-specific debugging.

## If you’re pasting into Codex (token-saving)
Prefer short, filtered output. Start with:
```
railway logs --lines 200 --filter "@level:error"
```
See: `docs/instructions/efficient-logs-for-codex.md`.

## Install
### Homebrew (macOS)
```
brew install railway
```

### npm (macOS/Linux/Windows)
```
npm i -g @railway/cli
```

### Shell script (macOS/Linux/WSL)
```
bash <(curl -fsSL cli.new)
```

### Scoop (Windows)
```
scoop install railway
```

## Authenticate
```
railway login
```

Browserless login (SSH/CI):
```
railway login --browserless
```

Token auth (CI or headless):
```
export RAILWAY_TOKEN=project-token
export RAILWAY_API_TOKEN=account-or-team-token
```

## Link a project (repo to Railway)
```
railway link
```

## Logs (most common)
```
# Stream logs from the latest deployment
railway logs

# Pull a fixed number of log lines
railway logs --lines 200

# JSON output for filtering
railway logs --lines 200 --json

# Filter logs by text or attributes
railway logs --lines 200 --filter "POST /tools"
railway logs --lines 200 --filter "@level:error"
```

Notes:
- `railway logs` streams by default. Use `--lines` (or `--tail`) for historical snapshots.
- `--service` and `--environment` scope logs if your project has multiple services/environments.

## Verify integration with LiveKit
See: `docs/instructions/verify-railway-livekit-sync.md`
