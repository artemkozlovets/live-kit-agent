---
name: commit
description: Generate a short commit message and commit current changes (explicit paths; no git add -A).
metadata:
  short-description: Fast commit with explicit paths
---

# Commit Helper (atomic, explicit paths)

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/commit/references/commit.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
We want commits that are easy to understand later (especially in future Codex
sessions). This skill:
- Writes a short commit message (summary + optional tiny body).
- Commits the current working changes using explicit paths derived from `git status`.
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
3) Build the commit file list from `git status --porcelain=v1` (all changes).
   - Exclude obvious junk files (e.g. `.DS_Store`) unless the user explicitly wants them.
   - For renames/copies (`old -> new`), include both paths so the delete/add is captured.
4) If any of those files are brand-new, stage only those paths:
   - `git add "path/to/file1" "path/to/file2"`
5) Gather change metadata (fast; no patch diffs):
   - Tracked edits/deletes: `git diff --name-status -- path/to/file1 path/to/file2` and `git diff --stat -- path/to/file1 path/to/file2`
   - Staged new files: `git diff --cached --name-status -- path/to/new_file1 path/to/new_file2` and `git diff --cached --stat -- path/to/new_file1 path/to/new_file2`
6) Generate a short commit message per the reference.
7) Commit using a multi-line message (safe quoting) and explicit paths, e.g.:
   - `git commit -m "$(cat <<'EOF' ... EOF)" -- path/to/file1 path/to/file2`
8) Print a short confirmation including the new commit hash and subject line.
