#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: missing ${ROOT}/.venv/bin/python" >&2
  echo "Fix: python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 2
fi

exec "$PY" "${ROOT}/scripts/livekit_cloud_smoke.py" "$@"

