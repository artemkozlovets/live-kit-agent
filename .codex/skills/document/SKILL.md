---
name: document
description: Create focused documentation for a specific part of this repo and save it under docs/documentations/.
metadata:
  short-description: Generate repo documentation
---

# Repo Documentation Writer

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/document/references/document.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
When someone asks “how does X work in this repo?”, we want a **clear, accurate markdown doc** that:
- Explains the behavior in plain English (not just code screenshots)
- Links to the real implementation files so a reader can click and verify
- Lives in this repo so it’s easy to share and version-control

## Full Playbook (untrimmed)
The long, detailed version of this workflow lives in:
- `.codex/skills/document/references/document.md`

Before writing documentation:
1. Read that file.
2. Follow it as the source of truth.
3. If it mentions `/document`, treat that as invoking this skill (`$document`).

## Approach (plain English)
1. **Clarify the question** (what feature/topic, and what’s the exact thing to explain?)
2. **Explore the code** (search, read, and trace the flow end-to-end)
3. **Write a short doc** in `docs/documentations/` using the repo’s existing style
4. **Prove it’s grounded** by adding file links (with line anchors when practical)

## Inputs to Ask For (if missing)
- **Topic name** (used for the filename)
  - Prefer `kebab-case` like existing docs: `api-server.md`, `n8n-workflows.md`
- **Question / goal** (1–2 sentences)
- **Scope** (optional): “only `api_server/`”, “only `server/`”, etc.

## Output Location
Write to: `docs/documentations/<topic-kebab-case>.md`

Use these as style references:
- `docs/documentations/api-server.md`
- `docs/documentations/squad-architecture.md`

## Research Checklist (do this before writing)
- Find entry points (routes, CLI entry, main modules)
- Identify core logic (services/handlers)
- Identify data layer (DB client, repositories, schemas)
- Identify integrations (external APIs, webhooks)
- Trace the **happy path** end-to-end (the normal, expected flow)

## Doc Template (keep it simple)
Create a doc shaped like this:

```md
# <Title>

> **Last Updated**: YYYY-MM-DD
> **Status**: Production | Beta | Draft

## Overview
2–4 sentences: what it does and why it exists.

## How It Works
Step-by-step flow (numbered list). Mention the key decision points.

## Key Components
- **<Component>** — purpose + link to file

## Data Flow (if relevant)
Input → processing → storage → output (simple diagram or bullets).

## Configuration (only if it exists)
- `ENV_VAR` — what it controls

## Notes / Gotchas
Edge cases, performance, security, limitations.
```

## File Links (how to format them)
Use clickable markdown links with line anchors when you reference a specific spot:
- `[fastapi_app.py:1-21](api_server/server/fastapi_app.py#L1-L21)`

## Quality Bar
- Don’t guess: only claim what you can back up by reading files.
- Keep code blocks small (≤ 10 lines) and only when it helps understanding.
- If you’re unsure, ask a clarifying question instead of inventing details.
