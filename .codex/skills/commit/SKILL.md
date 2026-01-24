---
name: commit
description: Generate a standardized commit message and output git commands to stage + commit.
metadata:
  short-description: Commit message generator
---

# ServiceBay Commit Message Generator

## REQUIRED: Read Reference First
Before doing anything else, open and read:
- `.codex/skills/commit/references/commit.md`

Do not proceed until it is read.

## Big Picture (what problem are we solving?)
We want commit messages to be consistent, descriptive, and easy to review.
This skill turns a short change description into a commit message that follows
ServiceBay’s conventions.

## Output Rule (VERY IMPORTANT)
When you produce the final output, print ONLY the git commands.
No explanations or extra text.
Format:
1) `git add -A`
2) `git commit -m "<MESSAGE>"`

## Automatic Mode (default)
Do not ask the user to fill in a template.

Instead, infer the commit message from the current git changes:
- Prefer staged changes (`git diff --cached`).
- If nothing is staged, use unstaged changes (`git diff`) and include untracked files from `git status --porcelain`.

This is an exception to "Learning Mode" verbosity: the final response must be
the commands only.
