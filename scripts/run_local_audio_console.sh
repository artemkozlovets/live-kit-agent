#!/usr/bin/env bash
set -euo pipefail

# Big picture: run backend + agent locally and save durable artifacts (logs + traces)
# into a per-run directory under ./local-observability/.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${ROOT}/local-observability/run-${RUN_ID}"

mkdir -p "$RUN_DIR"

# If you see `sysctlbyname('hw.logicalcpu') Operation not permitted`, set NUM_CPUS.
export NUM_CPUS="${NUM_CPUS:-2}"

export LOCAL_OBSERVABILITY_DIR="$RUN_DIR"
export USE_IN_MEMORY_DB=1
export LOG_LEVEL="${LOG_LEVEL:-DEBUG}"
export TOOLS_TOKEN="${TOOLS_TOKEN:-test-secret}"

# Backend connection details (override for parallel runs, or if port 8000 is in use).
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
export BACKEND_TOOLS_URL="${BACKEND_TOOLS_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/tools}"
export SESSION_REPORTS_URL="${SESSION_REPORTS_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}/observability/session-report}"

# Default: backend-first guardrails (agent calls get_case_status each turn).
export AGENT_BACKEND_GUARDRAILS="${AGENT_BACKEND_GUARDRAILS:-1}"

BACKEND_STDOUT_LOG="${RUN_DIR}/backend.stdout.log"

echo "Starting backend..."
"${ROOT}/.venv/bin/python" -m uvicorn api_server.server.fastapi_app:app \
  --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
  >"$BACKEND_STDOUT_LOG" 2>&1 &
BACKEND_PID=$!

cleanup() {
  if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Waiting for backend to be healthy..."
BACKEND_HEALTH_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/health"
for _ in $(seq 1 40); do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    echo ""
    echo "Backend failed to start (likely: port already in use)."
    echo "  - Check: $BACKEND_STDOUT_LOG"
    echo "  - Fix: stop whatever is using ${BACKEND_HOST}:${BACKEND_PORT}, or run with BACKEND_PORT=8001"
    exit 1
  fi
  if curl -fsS "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! curl -fsS "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
  echo ""
  echo "Backend did not become healthy at $BACKEND_HEALTH_URL"
  echo "  - Check: $BACKEND_STDOUT_LOG"
  exit 1
fi

echo ""
echo "Local run dir: $RUN_DIR"
echo "Artifacts:"
echo "  - $RUN_DIR/backend.log.jsonl"
echo "  - $RUN_DIR/backend.tools.jsonl"
echo "  - $RUN_DIR/session-reports/"
echo "  - $RUN_DIR/agent.log.jsonl"
echo "  - $RUN_DIR/backend.stdout.log"
echo ""

CONSOLE_MODE="${CONSOLE_MODE:-audio}"
CAPTURE_CONSOLE_LOG="${CAPTURE_CONSOLE_LOG:-0}"

agent_cmd=("${ROOT}/.venv/bin/python" -m livekit_agent.agent console)
if [[ "$CONSOLE_MODE" == "text" ]]; then
  echo "Starting agent console (text). Press Ctrl+C to stop."
  agent_cmd+=("--text")
else
  echo "Starting agent console (audio). Press Ctrl+C to stop."
  agent_cmd+=("--record")
fi

if [[ "$CAPTURE_CONSOLE_LOG" == "1" || "$CAPTURE_CONSOLE_LOG" == "true" ]]; then
  if command -v script >/dev/null 2>&1; then
    # Reason: console mode uses a rich TTY UI, so piping stdout/stderr breaks it.
    # `script` captures the full terminal output while preserving interactivity.
    CONSOLE_TTY_LOG="${RUN_DIR}/console.tty.log"
    echo "Capturing console output to: $CONSOLE_TTY_LOG"
    script -q "$CONSOLE_TTY_LOG" "${agent_cmd[@]}"
  else
    echo "WARNING: CAPTURE_CONSOLE_LOG=1 requested but 'script' is not available; running without capture." >&2
    "${agent_cmd[@]}"
  fi
else
  "${agent_cmd[@]}"
fi
