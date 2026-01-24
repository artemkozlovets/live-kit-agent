---
description: Generate standardized commit messages following ServiceBay conventions
tags: [git, commit, version-control, documentation]
---

# Commit Message Generator

IMPORTANT: Output ONLY the git commands. Do not include any explanations or
extra text.

Return either:
1) `git commit -m "<MESSAGE>" -- path/to/file1 path/to/file2` (tracked files; explicit paths)

Or, if the commit includes brand-new files:
1) `git restore --staged :/ && git add "path/to/file1" "path/to/file2" && git commit -m "<MESSAGE>" -- path/to/file1 path/to/file2`

## 🎯 ServiceBay Commit Format

### Structure
```
[Category] Brief summary (50-72 characters)
```

For complex changes, add sections:
- `## What Changed` or `## Problems Fixed`
- `## Root Causes` (for fixes)
- `## Solutions`
- `## Impact` (use ✅ / ⚠️ sparingly)
- `## Files Changed`

### Categories
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
