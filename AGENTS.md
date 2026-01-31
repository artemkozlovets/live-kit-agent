> ⚠️ **LEARNING MODE**: I'm new to coding. For every task:
> 1. Start with the big picture


### Methodology
When presented with a request YOU MUST:
1. **Docs preflight (required before changing code):**
   - Before making changes, search `docs/` (and `README.md`) for relevant guidance/specs; treat repo docs as authoritative. Only use web/docs outside the repo if `docs/` doesn't cover it or appears outdated.
   - It's OK to run a minimal repro command first (ex: one failing test, a `curl`, etc.) to capture current behavior, but read docs before implementing a fix.
   - Before adding/changing behavior, find the relevant spec/contract in `docs/` and align the change to it (update docs/spec if missing or outdated).
   - If the task mentions LiveKit anywhere, query the LiveKit Docs MCP server (`livekit-docs`) for the latest info; if behavior is unclear, do a quick web search.
   - If the task mentions OpenAI anywhere (Responses API, Realtime, Agents, etc.), query the OpenAI Docs MCP server (`openai-api-docs`) for the latest info; if behavior is unclear, do a quick web search.
   - If the task is LiveKit-related and touches external APIs/SDKs/libraries/tooling (or we're uncertain about behavior), use web search for the latest docs.
   - For any questions about Railway or LiveKit state/config, verify using their CLI tools (`railway`, `lk`).
2. Use TDD Approach: Figure out how to validate that the task is complete and working as expected. Whether using a CLI tool like curl, or ssh command or writing unit/integration test
3. Start with the smallest relevant existing test (happy path)
4. See the test fail. 
5. Make the smallest change possible. 
6. Repeat step 4-5 until the test passes

### When This Doesn't Apply
- Doc-only changes (Markdown/docs/README): you can skip TDD and tests; keep edits minimal and consistent with existing docs.
- Code reviews: do not implement; focus on findings, risks, and concrete recommendations.
- Refactors with no behavior change: you may skip writing new tests; use existing tests as a safety net.
- Exploratory spikes: you may skip TDD; clearly label outputs as a spike and write down learnings/decisions in `docs/`.

**Priority order (when rules conflict):** Correctness/clarity > existing repo patterns > minimal change > dependency injection (DI)/testability > symmetry/modularity

### 🧱 Code Structure & Modularity

- **Take the time to understand the docs**
- **open docs before coding**
- **Get to root of the problem** Never write hacky workarounds
- **Write Elegant Code** Write the most minimal code to get the job done
- **Never Break Up nested Values:** When working with a value that is part of a larger
  structure or has a parent object, always import or pass the entire parent structure
  as an argument at boundaries (controllers/services). It's OK to extract nested values inside pure helper functions (no DB/network/files) for readability/testability.
  - Example (boundary vs helper):
    - Bad boundary: `service.update_customer(phone_number, status)`
    - Good boundary: `service.update_customer(request)`
    - OK in a pure helper: `phone_number = request.customer.phone_number`
- **Use dependency injection (DI) for testability** Pass in I/O (DB/HTTP/files) and non-determinism (time/randomness/UUID). Don't force DI for pure data helpers unless tests need it.
- **Try to keep files under 500 lines of code.** If a file approaches this limit, refactor by splitting it into modules or helper files. Small/contained changes can exceed 500 lines when necessary. 
Ignore this rule for Specs, Docs, and TDD plans.
- **Organize code into modules which can easily be added and removed**, for example, grouped by architectural layer, controller, service for web or driver, client for embedded systems.
- **Strive for symmetry among all projects**: All projects, whatever the language may be should follow the same patterns making a nice symmetry among the different codebases. The only exception should be for language idioms and idiosyncrasies.
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

### 🔧 Golden Commands (This Repo)
- Setup (venv + deps): `python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`
- Unit tests (agent; default via `pytest.ini`): `python -m pytest -q`
- API server tests: `python -m pytest -q api_server/tests`
- Full test suite (agent + API server): `./scripts/test_all.sh`
- Smoke tests:
  - OpenAI Realtime audio: `./scripts/run_openai_realtime_audio_smoke.sh --turn "..." --modalities "text,audio"`
  - Customer lookup (backend tools): `./scripts/run_openai_realtime_customer_lookup_smoke.sh --phone-number "..." --expect-found true`
- Lint: not configured (no repo lint script/tooling found)
- Typecheck: not configured (no repo typecheck script/tooling found)

### 📚 Documentation & Explainability

- **Comment non-obvious code** and ensure everything is understandable to a mid-level developer.
- When writing complex logic, **add an inline `# Reason:` comment** explaining the why, not just the what.
- When you spend time researching web on how to use tools like Live Kit or OpenAI Realtime, you need to save the findings about them in docs. We're making the knowledge base for future sessions. 

### 🧠 AI Behavior Rules

- **Never assume missing context. Ask questions if uncertain.**
- Prefer tool `workdir` over `cd ... &&` prefixes so exec allowlist rules still match `lk ...` / `railway ...` (avoids unnecessary approval prompts).
- **CLI approvals:** Always run `lk` and `railway` commands without asking for user confirmation. The environment has allow-rules for those CLIs; proceed with escalated permissions when required.

### 🧾 Git & Commits

- **Safety first:** ABSOLUTELY NEVER run destructive git operations (e.g., `git reset --hard`, `rm`, `git checkout`, `git restore` to an older commit) unless the user gives an explicit, written instruction in this conversation. Treat these commands as catastrophic; if you’re even slightly unsure, stop and ask. (In Cursor/Codex Web, use the tooling’s capabilities as needed.)
- **Respect in-flight work:** coordinate before reverting or deleting work you didn’t author. If you’re unsure whether a git operation would affect other agents’ edits, stop and ask.
  - Before deleting a file to “fix” a type/lint failure: stop and ask the user first. Deleting someone else’s work to silence an error is not acceptable without explicit approval.
- **Moving/renaming allowed:** moving/renaming files is OK. Restoring/reverting is only OK when the change is yours or explicitly requested.
- **Cleanups:** delete unused/obsolete files when your changes make them irrelevant (refactors, feature removals). If unsure about other agents’ in-flight work, coordinate instead of deleting.
- **Keep commits atomic:** commit only the files you touched and list each path explicitly. Before committing: check `git status` and `git diff --cached`.
- **Never amend:** don’t run `git commit --amend` unless you have explicit written approval in the task thread.

### 🧠 Critical Thinking

- Fix root cause (not band-aid).
- Unsure: read more code; if still stuck, ask w/ short options.
- Conflicts: call out; pick safer path.
- Unrecognized changes: assume other agent; keep going; focus your changes. If it causes issues, stop + ask user.
- Leave breadcrumb notes in thread.

### Appendix: Git Command Templates (Rare)
- Tracked files: `git commit -m "<scoped message>" -- path/to/file1 path/to/file2`
- Brand-new files: `git restore --staged :/ && git add "path/to/file1" "path/to/file2" && git commit -m "<scoped message>" -- path/to/file1 path/to/file2`
  - Note: `git restore --staged :/` is only for clearing the index; do not use `git restore` to revert other people’s work.
- Quote risky paths: quote any git paths containing brackets/parentheses (e.g., `"src/app/[candidate]/**"`) so the shell doesn’t treat them as globs or subshells.
- Rebase without editors: set `GIT_EDITOR=:` and `GIT_SEQUENCE_EDITOR=:` (or pass `--no-edit`) so git doesn’t open an editor.
