#!/usr/bin/env sh
set -eu

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
  else
    PYTHON="python"
  fi
fi

"$PYTHON" -m pytest -q livekit_agent/tests
"$PYTHON" -m pytest -q api_server/tests
