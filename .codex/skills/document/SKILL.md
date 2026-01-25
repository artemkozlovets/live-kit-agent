---
name: document
description: Create Codex-first documentation (contracts/runbooks) for a specific part of this repo and save it under docs/.
metadata:
  short-description: Generate repo documentation
---

# Repo Documentation Writer

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/document/references/document.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
When someone asks “how does X work?” or “how do I do X?” in this repo, we want a **Codex-optimized markdown doc** that:
- Is **high-signal and unambiguous** (contracts, invariants, entrypoints, verification)
- Answers “**where do I look/change things?**” fast (paths + symbols + links)
- Includes a **proof path** (“how to verify”) so Codex can iterate safely
- Lives in the repo so it stays versioned and discoverable

## Full Playbook (untrimmed)
The long, detailed version of this workflow lives in:
- `.codex/skills/document/references/document.md`

Before writing documentation:
1. Read that file.
2. Follow it as the source of truth.
3. If it mentions `/document`, treat that as invoking this skill (`$document`).

## Approach (plain English)
1. **Clarify the doc type + objective**
   - “How it works / architecture / contract” → `docs/documentations/`
   - “How to do X (steps) / runbook” → `docs/instructions/`
2. **Explore the code**
   - Search + read + trace the happy path end-to-end
   - Identify invariants and “unsafe to assume” areas
3. **Write a Codex-first doc** using the repo’s existing style
4. **Ground every claim** with file links (use line anchors when practical)

## Inputs to Ask For (if missing)
- **Topic name** (used for the filename)
  - Prefer `kebab-case` like existing docs: `api-server.md`, `n8n-workflows.md`
- **Question / goal** (1–2 sentences)
- **Scope** (optional): “only `api_server/`”, “only `server/`”, etc.
- **Doc type** (optional): `documentation` (how it works) vs `instruction` (runbook)

## Output Location
Write to one of:
- `docs/documentations/<topic-kebab-case>.md` (how it works / contracts)
- `docs/instructions/<topic-kebab-case>.md` (how to do X / operational steps)

Use these as style references:
- `docs/README.md`
- `docs/documentations/README.md`
- `docs/documentations/repo-overview.md`
- `docs/documentations/livekit-agent.md`
- `docs/documentations/api-server.md`

## Research Checklist (do this before writing)
- Find entry points (routes, CLI entry, main modules)
- Identify core logic (services/handlers)
- Identify data layer (DB client, repositories, schemas)
- Identify integrations (external APIs, webhooks)
- Trace the **happy path** end-to-end (the normal, expected flow)

## Doc Template (Codex-first, high-signal)
Create a doc shaped like this (adjust sections as needed; keep it scannable):

```md
# <Title> (Codex Context)

> **Last Updated**: YYYY-MM-DD
> **Audience**: Codex (repo context)
> **Status**: Draft | Production | Deprecated

## TL;DR
- **Goal:** what this covers
- **Entry points:** the file(s)/symbol(s) to start from
- **Where to change:** the file(s) most likely to modify
- **How to verify:** exact command(s) to run

## Key Files
- `path/to/file.py` — why it matters
- `path/to/file.ts` — why it matters

## Flow (Happy Path)
1. Step 1 (include key decision points)
2. Step 2
3. Step 3

## Contracts / Invariants
- Assumption that must stay true
- “Do not break” constraints (API shapes, IDs, ordering, etc.)

## Configuration (only if it exists)
- `ENV_VAR` — what it controls

## Verification
- Happy path: `...` (expected success signal)
- Edge case: `...`
- Failure case: `...` (expected error)

## Failure Modes / Gotchas
- Symptom → likely cause → fix

## Related Docs
- `docs/...` (links)
```

## File Links (how to format them)
Use clickable markdown links with line anchors when you reference a specific spot:
- `[fastapi_app.py:1-21](api_server/server/fastapi_app.py#L1-L21)`

## Quality Bar
- Don’t guess: only claim what you can back up by reading files.
- Prefer **paths + symbols + commands** over narrative.
- Keep code blocks small (≤ 10 lines) and only when it helps verification.
- If you’re unsure, ask a clarifying question instead of inventing details.
