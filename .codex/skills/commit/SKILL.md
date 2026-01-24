---
name: commit
description: Generate a detailed commit message and create an atomic commit (explicit paths; no git add -A).
metadata:
  short-description: Atomic commit with explicit paths
---

# Commit Helper (atomic, explicit paths)

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/commit/references/commit.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
We want commits that are easy to understand later (especially in future Codex
sessions). This skill:
- Writes a multi-line commit message (subject + body) describing what/why/how.
- Creates an **atomic** commit (commit only the files you touched).
- Avoids the “stage everything” workflow (`git add -A`) so parallel agents can work safely in one repo.

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
2) Ensure the staging area is clean: `git diff --cached --name-only`
   - If anything is staged, stop and ask before changing the index.
3) Identify the exact files to commit (only the files you touched in this task).
4) If any of those files are brand-new, stage only those paths:
   - `git add "path/to/file1" "path/to/file2"`
5) Gather change data for just those paths:
   - Tracked edits/deletes: `git diff -- path/to/file1 path/to/file2`
   - Staged new files: `git diff --cached -- path/to/new_file1 path/to/new_file2`
6) Generate a detailed commit message per the reference.
7) Commit using a multi-line message (safe quoting) and explicit paths, e.g.:
   - `git commit -m "$(cat <<'EOF' ... EOF)" -- path/to/file1 path/to/file2`
8) Print a short confirmation including the new commit hash and subject line.
