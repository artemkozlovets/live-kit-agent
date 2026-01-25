> ⚠️ **LEARNING MODE**: I'm new to coding. For every task:
> 1. Start with the big picture


### Methodology
When presented with a request YOU MUST:
1. **Docs preflight (required before ANY tests or implementation):**
   - Before implementation, search `docs/` (and `README.md`) for relevant guidance/specs; treat repo docs as authoritative. Only use web/docs outside the repo if `docs/` doesn't cover it or appears outdated.
   - If the task mentions LiveKit anywhere, query the LiveKit Docs MCP server (`livekit-docs`) for the latest info; if behavior is unclear, do a quick web search.
   - If the task is LiveKit-related and touches external APIs/SDKs/libraries/tooling (or we're uncertain about behavior), use web search for the latest docs.
   - For any questions about Railway or LiveKit state/config, verify using their CLI tools (`railway`, `lk`).
2. Use TDD Approach: Figure out how to validate that the task is complete and working as expected. Whether using a CLI tool like curl, or ssh command or writing unit/integration test
3. Start with the smallest relevant existing test (happy path)
4. See the test fail. 
5. Make the smallest change possible. 
6. Repeat step 4-5 until the test passes

**Priority order (when rules conflict):** Correctness/clarity > existing repo patterns > minimal change > dependency injection (DI)/testability > symmetry/modularity

### 🧱 Code Structure & Modularity

- **Take the time to understand the docs**
- **open docs before coding**
- **Get to root of the problem** Never write hacky work arounds
- **Write Elegant Code** Write the most minimal code to get the job done
- **Never Break Up nested Values:** When working with a value that is part of a larger
  structure or has a parent object, always import or pass the entire parent structure
  as an argument at boundaries (controllers/services). It's OK to extract nested values inside pure helper functions (no DB/network/files) for readability/testability.
- **Use dependency injection (DI) for testability** Pass in I/O (DB/HTTP/files) and non-determinism (time/randomness/UUID). Don't force DI for pure data helpers unless tests need it.
- **Try to keep files under 500 lines of code.** If a file approaches this limit, refactor by splitting it into modules or helper files. Small/contained changes can exceed 500 lines when necessary. 
Ignore this rule for Specs, Docs, and Tdd plans.
- **Organize code into modules whcih can easily be added and removed**, for example, grouped by architectural layer, controller, service for web or driver, client for embedded systems.
- **Strive for symmetry among all projects**: All projects, whatever the language may be should follow the same patterns making a nice symmetry amoing the different codebases. The only exception should be for language idioms and idiosyncrasies.
- **Secrets are in .env**

### 🧪 Testing & Reliability
- **Do not change tests or config files without asking first:** If a test/config change is necessary, ask first with a brief reason + what would change. If after two attempts you cannot fix type/test errors without changing tests/config, stop and give me a full error output, and what you already tried.
But you can add new tests without approval.
- **Fail fast:** Let errors crash with stack traces. Only add error handling at system boundaries or when you have a specific recovery strategy.
- **After updating any logic**, run targeted tests while iterating, then run the full monorepo test suite before final handoff. Fix regressions. Alert if the tests need to be modified. DO NOT modify the tests automatically.
When writing tests, include:
  - 1 test for expected use
  - 1 edge case
  - 1 failure case

### 📚 Documentation & Explainability

- **Comment non-obvious code** and ensure everything is understandable to a mid-level developer.
- When writing complex logic, **add an inline `# Reason:` comment** explaining the why, not just the what.

### 🧠 AI Behavior Rules

- **Never assume missing context. Ask questions if uncertain.**
- Prefer tool `workdir` over `cd ... &&` prefixes so exec allowlist rules still match `lk ...` / `railway ...` (avoids unnecessary approval prompts).

### 🧾 Git & Commits

- **Safety first:** ABSOLUTELY NEVER run destructive git operations (e.g., `git reset --hard`, `rm`, `git checkout`, `git restore` to an older commit) unless the user gives an explicit, written instruction in this conversation. Treat these commands as catastrophic; if you’re even slightly unsure, stop and ask. (In Cursor/Codex Web, use the tooling’s capabilities as needed.)
- **Respect in-flight work:** coordinate before reverting or deleting work you didn’t author. If you’re unsure whether a git operation would affect other agents’ edits, stop and ask.
  - Before deleting a file to “fix” a type/lint failure: stop and ask the user first. Deleting someone else’s work to silence an error is not acceptable without explicit approval.
- **Moving/renaming allowed:** moving/renaming files is OK. Restoring/reverting is only OK when the change is yours or explicitly requested.
- **Cleanups:** delete unused/obsolete files when your changes make them irrelevant (refactors, feature removals). If unsure about other agents’ in-flight work, coordinate instead of deleting.
- **Keep commits atomic:** commit only the files you touched and list each path explicitly.
  - Before committing: check `git status` and `git diff --cached`.
  - For tracked files: `git commit -m "<scoped message>" -- path/to/file1 path/to/file2`
  - For brand-new files: `git restore --staged :/ && git add "path/to/file1" "path/to/file2" && git commit -m "<scoped message>" -- path/to/file1 path/to/file2`
    - Note: `git restore --staged :/` is only for clearing the index; do not use `git restore` to revert other people’s work.
- **Quote risky paths:** quote any git paths containing brackets/parentheses (e.g., `"src/app/[candidate]/**"`) so the shell doesn’t treat them as globs or subshells.
- **Rebase without editors:** set `GIT_EDITOR=:` and `GIT_SEQUENCE_EDITOR=:` (or pass `--no-edit`) so git doesn’t open an editor.
- **Never amend:** don’t run `git commit --amend` unless you have explicit written approval in the task thread.

### 🧠 Critical Thinking

- Fix root cause (not band-aid).
- Unsure: read more code; if still stuck, ask w/ short options.
- Conflicts: call out; pick safer path.
- Unrecognized changes: assume other agent; keep going; focus your changes. If it causes issues, stop + ask user.
- Leave breadcrumb notes in thread.
