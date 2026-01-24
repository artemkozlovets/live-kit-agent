---
name: commit
description: Generate a detailed commit message and run git add + git commit.
metadata:
  short-description: Auto-stage and commit with a detailed message
---

# Commit Helper (detailed, auto-stage + commit)

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/commit/references/commit.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
We want commits that are easy to understand later (especially in future Codex
sessions). This skill:
- Writes a multi-line commit message (subject + body) describing what/why/how.
- Stages changes.
- Creates the commit for you.

## Execution Rule (VERY IMPORTANT)
This skill should **run** the commands (via `functions.exec_command`), not just
print them.

If there are no changes to commit, stop and say so.

## Automatic Mode (default)
Do not ask the user to fill in a template.

Instead, infer the commit message from the current git changes and (when
available) the current session/task context.

Workflow:
1) Check status: `git status --porcelain=v1 -b`
2) Stage all changes: `git add -A`
3) Gather data from the staged snapshot:
   - `git diff --cached`
   - `git diff --cached --numstat`
   - `git diff --cached --name-status`
4) Generate a detailed commit message per the reference.
5) Commit using a multi-line message (safe quoting), e.g.:
   - `git commit -m "$(cat <<'EOF' ... EOF)"`
6) Print a short confirmation including the new commit hash and subject line.
