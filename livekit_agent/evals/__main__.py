from __future__ import annotations

import argparse
import asyncio
import os
import sys

from livekit_agent.evals.runner import exit_code, format_results, run_eval_suite
from livekit_agent.evals.scenarios import all_scenarios


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline eval suite for the LiveKit agent")
    parser.add_argument("--list", action="store_true", help="List available scenarios and exit")
    parser.add_argument("--scenario", action="append", default=[], help="Run only a matching scenario name")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-turn timeout (seconds)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))

    scenarios = all_scenarios()
    if args.list:
        for sc in scenarios:
            print(f"{sc.name} - {sc.description}")
        return 0

    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s.name in wanted]
        if not scenarios:
            print("No matching scenarios.", file=sys.stderr)
            return 2

    # Keep the output focused unless explicitly asked for verbose tracebacks.
    if os.getenv("EVALS_DEBUG_TRACEBACKS") != "1":
        sys.tracebacklimit = 0

    results = asyncio.run(run_eval_suite(scenarios, timeout_s=args.timeout))
    print(format_results(results))
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())

