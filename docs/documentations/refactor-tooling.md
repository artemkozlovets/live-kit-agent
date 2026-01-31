# Refactor Tooling (Codex Context)

> **Last Updated**: 2026-01-31  
> **Audience**: Codex (repo context)  
> **Status**: Draft

Big picture: this is a **repeatable “refactor work” checklist** (and toolbelt) for this repo—mirroring the spirit of:
> “jscpd for duplication, knip for dead code, eslint plugins for compiler/deprecations, consolidating routes, docs hygiene, breaking up large files, adding tests/comments, updating deps, and speeding up slow tests.”

The goal is to make these improvements **mechanical** (one command at a time) and **low-risk** (always paired with a verification command).

## TL;DR
- **Start here:** run the full suite `./scripts/test_all.sh` ([`scripts/test_all.sh`](../../scripts/test_all.sh#L1)).
- **Current baseline:** repo has pytest + smoke scripts, but no repo-level lint/typecheck toolchain yet (no `pyproject.toml` / pre-commit config).
- **Most valuable adds (Python equivalents):** `ruff`, `pyright`/`mypy`, `vulture`, `pylint` duplicate-code, `pip-audit`, `deptry`, `codespell`, `mdformat`.

## Current Baseline (What Exists Today)
- **Deps:** runtime + test deps are in [`requirements.txt`](../../requirements.txt) and [`requirements.backend.txt`](../../requirements.backend.txt).
- **Tests (default):** `pytest` only runs agent tests via [`pytest.ini`](../../pytest.ini#L1) (`testpaths = livekit_agent/tests`).
- **Tests (full):** run agent + API server tests via [`scripts/test_all.sh`](../../scripts/test_all.sh#L1).
- **FastAPI routes:** routers are mounted in [`api_server/server/fastapi_app.py`](../../api_server/server/fastapi_app.py#L109).

## Toolbelt (Python Mappings From the Article)

### Code duplication (jscpd equivalent)
Goal: detect “copy/paste blocks” worth extracting.

Options:
- **`pylint`** duplicate-code checker (`R0801`)
- **`jscpd`** (Node-based, but works well on Python too)

Commands:
- `python -m pip install pylint`
- `pylint --disable=all --enable=R0801 livekit_agent api_server`

Optional:
- `npx jscpd --languages python --path livekit_agent --path api_server`

### Dead code (knip equivalent)
Goal: find unused functions/classes/files that drift over time.

Options:
- **`vulture`** (static analysis heuristics)
- **`ruff`** (quick wins: unused imports/variables; not whole-program reachability)

Commands:
- `python -m pip install vulture`
- `vulture livekit_agent api_server --min-confidence 80`

### Lint + format (eslint equivalent)
Goal: fast feedback + safe auto-fixes.

Recommended:
- **`ruff`** (lint + import sorting + optional formatting)

Commands:
- `python -m pip install ruff`
- Lint: `ruff check .`
- Auto-fix: `ruff check . --fix`
- Format (if enabled): `ruff format .`

### Type checking (“compiler” signal)
Goal: catch broken assumptions early during refactors.

Options:
- **`pyright`** (fast, good defaults)
- **`mypy`** (highly configurable)

Commands:
- `python -m pip install pyright` then `pyright`
- (Alternative) `python -m pip install mypy` then `mypy livekit_agent api_server`

### Deprecations (eslint deprecation plugin equivalent)
Goal: surface Python/library deprecations before upgrades break production.

Commands:
- Treat deprecations as errors in tests:
  - `python -W error::DeprecationWarning -m pytest -q`
  - Full suite: `python -W error::DeprecationWarning -m pytest -q livekit_agent/tests api_server/tests`

### FastAPI route consolidation (API route cleanup)
Goal: avoid route sprawl and accidental overlaps.

Key entry point:
- Router mounting: [`api_server/server/fastapi_app.py`](../../api_server/server/fastapi_app.py#L109)

Command (print method + path):
```bash
PYTEST_CURRENT_TEST=1 python - <<'PY'
from api_server.server.fastapi_app import app
from fastapi.routing import APIRoute

routes = [r for r in app.routes if isinstance(r, APIRoute)]
for route in sorted(routes, key=lambda r: (r.path, tuple(sorted(r.methods)))):
    methods = ",".join(sorted(route.methods))
    print(f"{methods} {route.path} -> {route.endpoint.__module__}.{route.endpoint.__name__}")
PY
```

What to look for:
- Duplicate `METHOD + PATH` pairs (accidental duplicates).
- Routes that differ only by one segment (might consolidate).
- Routers that should share a prefix (group into a single router module).

### Docs hygiene (keep docs accurate)
Goal: reduce drift, broken links, and typos.

Options:
- **`mdformat`** (Markdown formatting)
- **`codespell`** (typo checks)

Commands:
- `python -m pip install mdformat codespell`
- Format docs: `find docs -name '*.md' -print0 | xargs -0 mdformat`
- Spellcheck docs: `codespell docs/ -q 3`

### Large files + complexity (file hygiene)
Goal: identify files that got too big (hard to refactor safely).

Commands:
- Largest files: `find livekit_agent api_server -name '*.py' -type f -print0 | xargs -0 wc -l | sort -n | tail -n 20`

Optional:
- `radon` / `xenon` for complexity gating

### Tests + slow tests
Goal: add tests while refactoring, and keep tests fast.

Repo commands:
- Full suite: `./scripts/test_all.sh` ([`scripts/test_all.sh`](../../scripts/test_all.sh#L1))
- Default (agent only): `python -m pytest -q` ([`pytest.ini`](../../pytest.ini#L1))
- API server tests: `python -m pytest -q api_server/tests`

Slow test detection:
- `python -m pytest -q --durations=20`
- `python -m pytest -q api_server/tests --durations=20`

Optional speedups:
- `python -m pip install pytest-xdist` then `python -m pytest -q -n auto`

### Dependency + tool upgrades
Goal: make upgrades incremental and safer.

Commands:
- Outdated: `python -m pip list --outdated`
- Broken deps: `python -m pip check`
- Security (optional): `python -m pip install pip-audit` then `pip-audit`
- Unused/missing deps (optional): `python -m pip install deptry` then `deptry .`

## Verification (Tight Loop)
- **Happy path:** `./scripts/test_all.sh`
- **Edge case:** `python -m pytest -q api_server/tests --durations=20` (confirm no pathological slow tests)
- **Failure case:** run one tool without installing it (ex: `ruff check .`) and confirm it fails fast with a clear “not installed” error

## Related Docs
- [`docs/documentations/testing-and-evals.md`](./testing-and-evals.md)
- [`docs/documentations/api-server.md`](./api-server.md)
