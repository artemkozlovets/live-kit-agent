---
description: Generate Codex-first repo documentation (contracts/runbooks) with file references and verification steps
tags: [documentation, codex, repo-context, runbook, contracts]
---

# Codex-First Documentation Generator

Generate high-signal documentation optimized for Codex-style codebase work: fast retrieval, explicit contracts, and “how to verify” commands. Output should be useful even if no human ever reads it.

## Purpose

This skill produces docs that answer:
- What is this and what does it affect?
- Where are the entrypoints and the core logic?
- What invariants/contracts must remain true?
- What commands prove it still works (happy path + edge + failure)?

## User Input Required

When invoking this command, the user should provide:
- **Topic name** (kebab-case; used for filename)
- **Objective/question** (1–2 sentences)
- **Scope** (optional): specific directories/files/components to focus on
- **Doc type** (optional): `documentation` (how it works) vs `instruction` (runbook)

## Research Process (Required)

Before writing anything, you MUST:

### 0. Docs preflight (required)
- Read `docs/README.md` and `docs/documentations/README.md`
- If a doc already exists for this topic/area, update it instead of creating a duplicate
- Treat `docs/` as the source of truth for repo behavior unless code contradicts it

### 1. Explore the codebase thoroughly
- Use `rg` to find entrypoints, call sites, and key symbols
- Read the code (don’t infer from filenames)
- Trace the happy path end-to-end (the normal, expected flow)

### 2. Identify key components
- Entry points (routes, webhooks, endpoints)
- Core logic (services, managers, handlers)
- Data layer (repositories, schemas, migrations)
- Integration points (external APIs, WebSocket)
- Configuration (environment variables, constants)

### 3. Extract contracts + verification
- Contracts/invariants (payload shapes, IDs, ordering, retries, side effects)
- Verification commands (prefer existing tests; include happy path + edge + failure)

## Output Location

Write to one of:
- `docs/documentations/<topic-name>.md` (how it works / contracts)
- `docs/instructions/<topic-name>.md` (how to do X / operational runbook)

If the user doesn’t specify, infer from phrasing:
- “How does X work?” → `docs/documentations/`
- “How do I do X?” → `docs/instructions/`

## Documentation Template (Codex-first)

Use this shape (adapt as needed; keep it scannable):

```markdown
# [Title] (Codex Context)

> **Last Updated**: YYYY-MM-DD
> **Audience**: Codex (repo context)
> **Status**: Draft | Production | Deprecated

## TL;DR
- **Goal:** what this doc covers
- **Entry points:** where to start reading
- **Where to change:** files most likely to modify
- **How to verify:** exact command(s) to run

## Key Files
- `path/to/file.py` — why it matters
- `path/to/file.ts` — why it matters

## Flow (Happy Path)
1. Step 1 (include key decision points)
2. Step 2
3. Step 3

## Contracts / Invariants
- Assumption that must remain true
- “Do not break” constraints (API shapes, IDs, ordering, etc.)

## Configuration
## Verification
- Happy path: `...` (expected success signal)
- Edge case: `...`
- Failure case: `...` (expected error)

## Failure Modes / Gotchas
- Symptom → likely cause → fix

## Related Docs
- `docs/...` (links)
```

If writing a pure runbook (`docs/instructions/`), you can use the same template but prioritize **steps + verification**.

## Writing Guidelines

### DO:
- Prefer bullet lists over prose
- Use exact tokens Codex can grep (paths, symbols, env vars, endpoint paths)
- Include verification commands and expected success signals
- State contracts/invariants explicitly
- Link to source with file paths and line anchors when practical

### DON'T:
- Don’t guess or “probably”; either verify in code or ask a clarifying question
- Don’t paste huge logs/output into docs (keep it low-noise and searchable)
- Don’t include large code blocks (keep ≤ 10 lines, only for verification/examples)

## File Link Format

Always use clickable markdown links with line numbers:

**Format**: `[display-text](relative/path/to/file.py#L123)`

**Examples**:
- `[livekit_agent/agent.py](livekit_agent/agent.py)`
- `[fastapi_app.py](api_server/server/fastapi_app.py#L123)` (example line anchor)
- `[tools.py](livekit_agent/tools.py#L45-L67)` (example range)

**Tips**:
- Use relative paths from repository root
- Include line numbers when referencing specific code
- Use descriptive text (not just "click here")
- Format: `#L123` for single line, `#L123-L145` for range

## Documentation Examples

### Example 1: Feature Documentation
**User Request**: "Document the LiveKit agent tool-calling flow"

**Your Process**:
1. Read `docs/documentations/livekit-agent.md` (if it exists) and update if needed
2. Trace the runtime starting at `livekit_agent/agent.py`
3. Identify backend tool contract boundaries (`livekit_agent/backend_tools_client.py`, `api_server/`)
4. Write `docs/documentations/livekit-agent-tool-calling.md` with TL;DR + contracts + verification

### Example 2: Specific Question
**User Request**: "How do migrations work?"

**Your Process**:
1. Read `docs/documentations/database-and-migrations.md` and update if needed
2. Trace how migrations run (scripts, CLI entrypoints, config)
3. Write a focused doc with commands + expected outputs

### Example 3: Technical Concept
**User Request**: "How do I pull Railway logs for the agent?"

**Your Process**:
1. Read existing runbooks in `docs/instructions/`
2. Create/update `docs/instructions/pull-railway-logs.md` with steps + verification

## Completion Summary

After creating documentation, provide the user with:

```markdown
## Documentation Complete

**Created**: `docs/documentations/<topic-name>.md` or `docs/instructions/<topic-name>.md`

**What's Included**:
- TL;DR (entrypoints + where-to-change + verification)
- Key files and happy path flow
- Contracts/invariants
- Verification commands (happy + edge + failure)
- Failure modes/gotchas

**Key Files Documented**:
- [File 1](path) - Brief description
- [File 2](path) - Brief description
- [File 3](path) - Brief description

**Related Docs**:
- `docs/...` links
```

## Quick Start

**For Users**:
1. Invoke: `$document`
2. Specify what to document: "Document the [feature/topic]"
3. Wait for exploration and documentation
4. Review the generated markdown under `docs/`

**For the Agent (Codex CLI)**:
1. Restate the objective and decide output path (`docs/documentations/` vs `docs/instructions/`)
2. Use `rg` + file reads to discover entrypoints and trace the happy path
3. Capture contracts/invariants and verification commands
4. Write the doc using the template (paths + symbols + commands; minimal prose)
5. Save to `docs/<...>/<topic-name>.md` and provide a short completion summary

## Advanced Features

### Code Block Usage (Minimal)
Only include code blocks when:
- Showing configuration examples
- Demonstrating API usage
- Explaining complex logic that needs visual reference

Keep code snippets to **5-10 lines maximum**.

### Diagrams (Optional)
Use simple text-based flow when helpful:
```
Client → LiveKit Room → `livekit_agent/` → backend tools (`api_server/`) → database
```

### Cross-References
Link to other documentation when features are related:
- `docs/documentations/` (how it works / contracts)
- `docs/instructions/` (operational runbooks)
- `docs/README.md` (docs load order)

## Pro Tips

1. **Start Broad, Then Narrow**: Explore the entire feature area before focusing on details
2. **Follow the Flow**: Trace the actual execution path through the code
3. **Prefer contracts**: Write down invariants and verification, not narrative
4. **Check Recent Changes**: Look at git history for context on why things exist
5. **Link Generously**: More links = faster navigation for Codex
6. **Update Existing**: If documentation already exists, update instead of recreate

## Quality Checklist

Before completing, verify:
- [ ] Docs preflight completed (`docs/` reviewed)
- [ ] Thorough codebase exploration performed (happy path traced)
- [ ] All key components identified and explained
- [ ] File links are accurate with correct line numbers
- [ ] Contracts/invariants are explicit
- [ ] Verification commands exist (happy + edge + failure)
- [ ] No assumptions - everything based on actual code
- [ ] Concise but complete
- [ ] Saved to `docs/documentations/` or `docs/instructions/`
- [ ] Summary provided to user

---

**Ready to generate accurate, Codex-first documentation for any part of this repo.**
