import os

import pytest

os.environ.setdefault("NUM_CPUS", "2")

try:
    import livekit.agents  # noqa: F401
except Exception as exc:  # pragma: no cover
    pytest.skip(f"livekit.agents unavailable in this environment: {exc}", allow_module_level=True)

from livekit_agent.evals.runner import run_eval_suite  # noqa: E402
from livekit_agent.evals.scenarios import all_scenarios  # noqa: E402


@pytest.mark.asyncio
async def test_offline_eval_suite_passes() -> None:
    results = await run_eval_suite(all_scenarios(), timeout_s=2.0)
    failures = [r for r in results if not r.ok]
    assert not failures, "\n".join(f"{f.scenario.name}: {f.error}" for f in failures)

