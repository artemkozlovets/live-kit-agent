#!/usr/bin/env sh
set -eu

MODE="${MODE:-start}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

exec python -m livekit_agent.agent "$MODE" --log-level "$LOG_LEVEL"

