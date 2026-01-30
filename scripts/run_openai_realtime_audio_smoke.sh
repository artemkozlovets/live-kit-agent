#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# If you see `sysctlbyname('hw.logicalcpu') Operation not permitted`, set NUM_CPUS.
export NUM_CPUS="${NUM_CPUS:-2}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is required." >&2
  exit 2
fi

"${ROOT}/.venv/bin/python" -m livekit_agent.openai_realtime_audio_smoke "$@"
