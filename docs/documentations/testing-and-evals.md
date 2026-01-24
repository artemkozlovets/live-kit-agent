# Testing + Evals

> **Last Updated**: 2026-01-24  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- Default `pytest` target is the agent tests (`livekit_agent/tests`) via `pytest.ini`.
- There is also an offline eval suite (conversation-level scenarios, no network).

## Pytest
By default, pytest is configured to run only `livekit_agent/tests`:
- Config: [`pytest.ini`](../../pytest.ini)

### Run agent tests (default)
```bash
python -m pytest -q
```

### Run API server tests
There is also a test suite under `api_server/tests/`, but it is not included in `pytest.ini`’s `testpaths`.

Run it explicitly:
```bash
python -m pytest -q api_server/tests
```

## Offline eval suite
The eval suite simulates a multi-turn conversation by:
- feeding user turns to the agent
- intercepting backend tool calls
- returning deterministic tool results
- asserting ordering (speak-first vs tool-first vs update-first)

Entrypoint: `livekit_agent/evals/__main__.py`  
Runner: `livekit_agent/evals/runner.py`  
Scenarios: `livekit_agent/evals/scenarios.py`

### Run evals
```bash
python -m livekit_agent.evals
```

### List scenarios
```bash
python -m livekit_agent.evals --list
```
