---
name: spec
description: Plan a feature via Socratic Q&A and write a living spec in docs/specs/.
metadata:
  short-description: Socratic feature spec builder
---

# Feature Spec Builder

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/spec/references/spec.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
Feature ideas are often fuzzy. This skill turns a vague idea into a **written spec**
that is clear enough to implement and review.

## Full Playbook (untrimmed)
The long, detailed version of this workflow lives in:
- `.codex/skills/spec/references/spec.md`

Before starting:
1. Read that file.
2. Follow it as the source of truth.
3. If it mentions `/spec`, treat that as invoking this skill (`$spec`).

## Approach (plain English)
1. Pick a spec name and create the file in `docs/specs/`
2. Ask **one question at a time**, going a layer deeper with “why?” once
3. Update the spec file as we learn things (so it stays the source of truth)
4. Do quick codebase recon to identify integration points
5. Mark it “Ready for Review”, then “Approved” when the user agrees

## Step 1: Name + Create Spec File
Ask: “What should we name this spec?” (use `snake_case` like `postgres_connection.md`)

Create: `docs/specs/<name>.md` with:

```md
# Feature Spec: <Name>

> Created: YYYY-MM-DD
> Status: 🔴 Discovery

---

<!-- Sections added as we discuss -->
```

Use this as a style reference:
- `docs/specs/postgres_connection.md`

## Step 2: Socratic Q&A Loop
Rules:
- Ask **1 question** at a time.
- After the answer, ask **one “why?”** follow-up (to get the real reason).
- After each meaningful answer, **update the spec** (don’t wait until the end).
- Before switching topics, summarize what you understood and confirm it.

Good question areas (pick what’s missing next):
- Problem: who is affected, what breaks, what happens if we do nothing?
- Solution: simplest version, user workflow, what “done” looks like
- Edge cases: failures, invalid inputs, worst bug scenario
- Success: how do we verify it works (tests, logs, metrics)?

## Step 3: Codebase Recon (after requirements are clearer)
Search this repo for where the feature should plug in:
- entry points (routers/handlers)
- data access layer
- existing patterns we should follow

Add an **Integration** section naming the files/modules involved (with links).

## Step 4: Synthesize Requirements
Add a `## Requirements` section:

```md
## Requirements

### Must-Have
- [ ] ...

### Nice-to-Have
- [ ] ...

### Out of Scope
- [ ] ...
```

Ask: “Anything wrong or missing?”

## Step 5: Finalize
- Update status → `🟡 Ready for Review`
- Ask for approval
- On approval, update status → `🟢 Approved`
