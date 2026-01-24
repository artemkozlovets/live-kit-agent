# Commit Message Generator (ServiceBay)

## Output Rule (VERY IMPORTANT)
When producing the final answer, output **ONLY** the git commands.
Do not include explanations or any extra text.
Format:
1) `git add -A`
2) `git commit -m "<MESSAGE>"`

## ServiceBay Commit Format

### Summary line (always required)
```
[Category] Brief summary (50-72 characters)
```

Rules:
- Start with the category in brackets.
- Use imperative mood: "Add", "Fix", "Update", "Remove", "Refactor".
- Keep the summary line ≤ 72 characters total (including `[Category] `).
- Be specific (avoid “updates”, “various fixes”).

### Complex commits (add body sections)
For significant changes, add a body with sections (in this order when relevant):

Required sections for complex commits:
- `## What Changed` **or** `## Problems Fixed`
- `## Solutions`
- `## Impact`
- `## Files Changed`

Additionally required for fixes:
- `## Root Causes` (required for `[Critical Fix]` and `[Temporary Rollback]`)

Optional sections:
- `## Testing Notes`
- `## Related Issues/PRs`
- `## Next Steps`

Formatting rules:
- Use bullets (`- ...`) for readability.
- Impact lines use emojis sparingly:
  - Prefix positives with `✅`
  - Prefix caveats with `⚠️`
  - Prefix critical risks with `🔴`
- Files use repo-relative paths and include line numbers / sections when possible.

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
Do not ask the user to fill in a template.

Infer the commit message from the current git changes.
Do not ask follow-up questions; if anything is ambiguous, choose the simplest
accurate one-line message.

After generating the message, emit the two commands in the required format.

### 1) Gather change data (staged preferred)
- Check status: `git status --porcelain=v1 -b`
- If staged changes exist, use:
  - `git diff --cached`
  - `git diff --cached --numstat`
- If nothing is staged, use:
  - `git diff`
  - `git diff --numstat`
  - Include untracked files from `git status --porcelain` as `(new)`

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
- Base the nouns/verbs on what actually changed in the diff (don’t guess).

### 4) Simple vs complex (automatic)
Use the **simple** one-line format when changes are small and focused.
Use the **complex** format when the change spans multiple files/components or is large.

When you choose the complex format, include (at minimum):
- `## What Changed` **or** `## Problems Fixed`
- `## Solutions`
- `## Impact` (✅ for positives; ⚠️ for caveats the diff implies)
- `## Files Changed` (repo-relative paths + `(new)` or `(+A/-D)` from `--numstat`)

## Decision Rules (how to generate)
1. **Pick the category** from the allowed list (normalize obvious variants like `critical fix` → `Critical Fix`).
2. **Write the summary** in imperative mood and keep ≤ 72 chars total.
3. **Simple vs complex**
   - If the change is straightforward, output only the summary line.
   - If the change is significant OR the user provides multi-part context, output the complex format.
4. **Complex requirements**
   - Must include `What Changed` or `Problems Fixed`.
   - Must include `Solutions`, `Impact`, `Files Changed`.
   - If category is `[Critical Fix]` or `[Temporary Rollback]`, include `Root Causes`.
5. **Impact markers**
   - Default to `✅` for positive outcomes unless the user explicitly marks a caveat/risk.

## Examples

### Simple
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

## Solutions
- WebSocket client in lib/websocket-client.ts
- Map component using react-leaflet
- useGPSTracker custom hook for state management

## Impact
✅ Real-time technician tracking
✅ Improved dispatcher visibility
✅ Reduced manual check-in calls

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

## Impact
✅ No dead air in conversation flow
✅ Natural conversation progression
✅ Improved user experience

## Files Changed
- packages/api/src/websocket/voice-stream-manager.ts (lines 893-901)
```
