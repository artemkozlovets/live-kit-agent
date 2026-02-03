# Commit Helper (atomic, explicit paths)

## Output Rule (VERY IMPORTANT)
When producing the final answer, **run** the commands (don’t just print them):
1) `git diff --cached --name-only` (must be empty; don’t touch the index if it isn’t)
2) `git commit -m "<MESSAGE>" -- path/to/file1 path/to/file2` (tracked files; explicit paths)

If the commit includes brand-new files, use the one-liner:
- `git restore --staged :/ && git add "path/to/file1" "path/to/file2" && git commit -m "<MESSAGE>" -- path/to/file1 path/to/file2`

After committing, print a short confirmation (commit hash + subject line).

## Commit Format (default: short)

### Summary line (always required)
```
[Category] Brief summary (50-72 characters)
```

Rules:
- Start with the category in brackets.
- Use imperative mood: "Add", "Fix", "Update", "Remove", "Refactor".
- Keep the summary line ≤ 72 characters total (including `[Category] `).
- Be specific (avoid “updates”, “various fixes”).

### Body (optional; keep it tiny)
Default to **no body** unless it adds real value. If you add one, prefer 3–10 lines max.

Recommended minimal body template:
```
Files:
- path/to/file1
- path/to/file2

How to verify:
- Not run
```

If you have `--stat` output that’s short, it’s okay to include it instead of the
file list, but do **not** paste full patch diffs.

Optional sections:
- `Why` (only when the user asked for it / task context is clear)
- `How to verify` (only if you actually ran commands)

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
- `[Chore]` - Misc changes / “commit current work”
- `[Merge]` - Merge commits
- `[Checks]` - CI/CD, GitHub Actions
- `[Temporary Rollback]` - Temporary reverts

## Automatic Mode (default)
Do not ask the user to fill in a template.

Default behavior: commit **everything currently shown in** `git status --porcelain=v1`
(minus obvious junk like `.DS_Store`). Only stop and ask if:
- The user asked for a scoped/atomic commit, or
- The status includes likely-unwanted files and you need confirmation.

### 1) Gather change metadata (fast; no patch diffs)
- Check status: `git status --porcelain=v1 -b`
- Ensure staging is empty: `git diff --cached --name-only`
- Build the file list from `git status --porcelain=v1` output (plus any brand-new files you stage).
- Use **metadata-only** diffs scoped to that file list:
  - `git diff --name-status -- path/to/file1 path/to/file2`
  - `git diff --stat -- path/to/file1 path/to/file2`
  - If you staged any brand-new files: `git diff --cached --name-status -- path/to/new_file1` and `git diff --cached --stat -- path/to/new_file1`

### 2) Pick the category (heuristics)
Choose the most fitting category based on the files/changes:
- Only `docs/` or `*.md` → `[Docs]`
- Only tests (`test_*.py`, `*_test.py`, `*/tests/*`) → `[Test]`
- Only CI (`.github/`, workflows) → `[Checks]`
- Only infra/config (`Dockerfile`, `requirements.txt`, `railway.json`, `.env.example`, etc.) → `[Config]`
- Only `.codex/` (new/updated Codex tools) → `[Feature]`
- Mostly deletions / dead code removal → `[Cleanup]`
- Mostly restructures/renames without behavior change → `[Refactor]`
- Otherwise / mixed changes → `[Chore]`

Avoid `[Critical Fix]` / `[Temporary Rollback]` unless the diff clearly shows a bug fix
and you can write a non-speculative `Root Causes` section.

### 3) Generate the summary line (always)
- Imperative mood, specific, ≤ 72 chars total (including `[Category] `).
- Base nouns/verbs on what you can infer from filenames and `--stat/--name-status` (don’t guess).

### 4) Body (default: omit)
If you include a body, limit it to file list (and optional “Not run” verify line).

## Decision Rules (how to generate)
1. **Pick the category** from the allowed list (normalize obvious variants like `critical fix` → `Critical Fix`).
2. **Write the summary** in imperative mood and keep ≤ 72 chars total.
3. **No speculation**: if you can’t justify a claim from filenames / stats / context, omit it.
4. **Testing honesty**: only claim tests ran if they actually ran in this session.

## Examples

### Fast (default)
```
[Chore] Commit current changes

Files:
- livekit_agent/openai_realtime_agent.py
- livekit_agent/tests/test_openai_realtime_agent_language_preference.py (new)

How to verify:
- Not run
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
