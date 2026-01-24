---
name: tdd-implementation
description: Execute a markdown TDD plan from a `*tdd*.md` file step-by-step. Use when asked to “implement the plan at …tdd.md”, run the verification for each step (pytest), debug/iterate until it passes, then record progress + design decisions back into the plan.
metadata:
  short-description: Execute TDD plans step-by-step
---

# TDD Implementation

## Big Picture (what problem are we solving?)
When you have a written TDD plan, it’s easy to lose track of which step you’re on, which tests you ran, and what design choices you made. This skill enforces a repeatable loop:

Plan step → run the test → make the smallest change → re-run → log completion + decisions → next step.

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/tdd-implementation/references/tdd-implementation.md`

Do not proceed until it is read.
