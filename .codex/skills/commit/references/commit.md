# Commit Helper (detailed, auto-stage + commit)

## Output Rule (VERY IMPORTANT)
When producing the final answer, **run** the commands (don’t just print them):
1) `git add -A`
2) `git commit -m "<MESSAGE>"` (use a safe multi-line form, e.g. `git commit -m "$(cat <<'EOF' ... EOF)"`)

After committing, print a short confirmation (commit hash + subject line).

## Commit Format (default: include a body)

### Summary line (always required)
```
[Category] Brief summary (50-72 characters)
```

Rules:
- Start with the category in brackets.
- Use imperative mood: "Add", "Fix", "Update", "Remove", "Refactor".
- Keep the summary line ≤ 72 characters total (including `[Category] `).
- Be specific (avoid “updates”, “various fixes”).

### Body (default: include these sections)
Use markdown-style headings and bullets for readability. Keep every statement
grounded in the diff and/or the current session context (don’t speculate).

Required sections:
- `## What Changed` **or** `## Problems Fixed`
- `## Why` (use current task/session intent when available)
- `## How to Verify` (tests/commands you actually ran; otherwise explicitly say `Not run`)
- `## Files Changed` (repo-relative paths, one per line)

Additionally required for certain categories:
- `## Root Causes` (required for `[Critical Fix]` and `[Temporary Rollback]`, but only when it is clear from the diff/context)

Optional sections:
- `## Solutions` (useful for multi-file changes)
- `## Impact` (user-facing behavior, performance, ops, etc.)
- `## Related Issues/PRs`
- `## Next Steps`

Formatting rules:
- Use bullets (`- ...`) for readability.
- Avoid emojis.
- Files use repo-relative paths and include brief qualifiers when helpful: `(new)`, `(delete)`, `(rename)`.

## Categories
Use one of these category prefixes:

- `[Critical Fix]` - Production bugs, pipeline issues, UX problems
- `[Feature]` - New features or major functionality
- `[Refactor]` - Code restructuring without behavior change
- `[Model Update]` - LLM model changes
- `[Docs]` - Documentation updates
- `[Test]` - Test additions or modifications
- `[Config]` - Configuration changes
- `[Cleanup]` - Code cleanup, removing dead code
- `[Merge]` - Merge commits
- `[Checks]` - CI/CD, GitHub Actions
- `[Temporary Rollback]` - Temporary reverts

## Automatic Mode (default)
Do not ask the user to fill in a template or ask follow-up questions.

### 1) Gather change data (use the staged snapshot)
- Check status: `git status --porcelain=v1 -b`
- Stage all changes: `git add -A`
- Use staged diff for analysis:
  - `git diff --cached`
  - `git diff --cached --numstat`
  - `git diff --cached --name-status`

### 2) Pick the category (heuristics)
Choose the most fitting category based on the files/changes:
- Only `docs/` or `*.md` → `[Docs]`
- Only tests (`test_*.py`, `*_test.py`, `*/tests/*`) → `[Test]`
- Only CI (`.github/`, workflows) → `[Checks]`
- Only infra/config (`Dockerfile`, `requirements.txt`, `railway.json`, `.env.example`, etc.) → `[Config]`
- Only `.codex/` (new/updated Codex tools) → `[Feature]`
- Mostly deletions / dead code removal → `[Cleanup]`
- Mostly restructures/renames without behavior change → `[Refactor]`

Avoid `[Critical Fix]` / `[Temporary Rollback]` unless the diff clearly shows a bug fix
and you can write a non-speculative `## Root Causes` section.

### 3) Generate the summary line (always)
- Imperative mood, specific, ≤ 72 chars total (including `[Category] `).
- Base nouns/verbs on what actually changed in the diff (don’t guess).

### 4) Always include a body (default)
Default to the multi-line format with the required sections, even for small
changes. Keep it short (2-6 bullets per section).

## Decision Rules (how to generate)
1. **Pick the category** from the allowed list (normalize obvious variants like `critical fix` → `Critical Fix`).
2. **Write the summary** in imperative mood and keep ≤ 72 chars total.
3. **Write the required body sections** (`What Changed/Problems Fixed`, `Why`, `How to Verify`, `Files Changed`).
4. **No speculation**: if you can’t justify a claim from the diff/context, omit it or phrase it conservatively.
5. **Testing honesty**: only claim tests ran if they actually ran in this session.

## Examples

### Simple (rare; only when explicitly requested)
```
[Feature] Add user profile page with avatar upload
```

### Feature with details
```
[Feature] Add GPS tracker WebSocket integration for dispatcher-web

## What Changed
- Real-time location updates via WebSocket
- Map component with technician markers
- Auto-reconnect on connection loss

## Why
- Provide real-time technician visibility without manual refresh

## How to Verify
- Not run

## Solutions
- WebSocket client in lib/websocket-client.ts
- Map component using react-leaflet
- useGPSTracker custom hook for state management

## Files Changed
- apps/dispatcher-web/src/lib/websocket-client.ts (new)
- apps/dispatcher-web/src/hooks/use-gps-tracker.ts (new)
- apps/dispatcher-web/src/components/gps-map.tsx (new)
```

### Critical fix with context
```
[Critical Fix] Resolve voice pipeline dead air after contact collection

## Problems Fixed
- Agent says "Got it" after receiving contact number, then hangs for 12+ seconds
- User must prompt again to continue the call

## Root Causes
- Duplicate contact detection returned early, skipping follow-up logic
- LLM lacked guidance on the next required field

## Solutions
- Continue to next field instead of returning early on duplicates
- Prompt next question immediately after acknowledging contact

## How to Verify
- Not run

## Files Changed
- packages/api/src/websocket/voice-stream-manager.ts (lines 893-901)
```
