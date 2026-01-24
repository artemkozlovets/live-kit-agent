# TDD Implementation (Reference)

## Inputs to ask for (if missing)
- The plan file path (must be a markdown file, usually matching `*tdd*.md`)
- How to run tests in this repo (default: `pytest`)
- Whether you want to run only targeted tests per step, or the full suite each time (default: targeted per step, full suite at the end)

## Step format (what this runner understands)
The runner expects the plan to contain **one of**:

1) A markdown table with `Step` + `Test` columns, like:
   - `| 1.1.1 | test_validate_phone_valid_number | {"valid": True} | ... |`

2) Headings like `### Test 1.1.1: ...` with a code block containing a `def test_...` function.

Implementation helper (optional): `squad/scripts/tdd_plan_runner.py` can parse both formats and append execution log entries.

## The loop (do this for every step)
1) **Pick the next step**
   - Parse the plan to find steps and their test selectors.
   - Look for completed steps in `## TDD Execution Log` entries like `- ✅ 1.1.1 ...`
   - Choose the first step not yet completed.

2) **Run verification first**
   - Run the step’s test (targeted) and confirm it passes.
   - Default command pattern: `pytest -k <test_selector>`

3) **If it fails: debug + iterate**
   - Re-run the same test until it passes.
   - Make the smallest change that fixes the failure.
   - Follow repo rules: prefer dependency injection for time/random/IO, don’t change existing tests/config without asking.

4) **Record progress + decisions in the plan**
   - Append to the plan under `## TDD Execution Log`:
     - Which step you completed
     - What command you ran to verify
     - A short design decision note (the “why”)

Suggested log format:
```md
## TDD Execution Log

- ✅ 1.1.1 (2026-01-16T12:34:56Z) `pytest -k test_example`
  - Decision: Chose DI for time source so tests are deterministic.
```

5) **Move to the next step**

## End-of-plan verification
After all steps are complete, run the full test suite (repo standard) before final handoff.
