#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# If you see `sysctlbyname('hw.logicalcpu') Operation not permitted`, set NUM_CPUS.
export NUM_CPUS="${NUM_CPUS:-2}"

"${ROOT}/.venv/bin/python" -m livekit_agent.openai_realtime_voice_smoke "$@"

