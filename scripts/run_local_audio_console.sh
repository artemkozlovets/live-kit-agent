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
export VAPI_TOOLS_LOG_TIMING="${VAPI_TOOLS_LOG_TIMING:-1}"
export BACKEND_TOOLS_URL="http://127.0.0.1:8000/vapi/tools"
export SESSION_REPORTS_URL="http://127.0.0.1:8000/observability/session-report"

# Local UX defaults (override at invocation time if needed):
# - Fast intake: greet + accept an info dump on the first user turn (no callback gate).
# - Deterministic get_case_status: avoid network calls inside the critical path.
export AGENT_FAST_INTAKE="${AGENT_FAST_INTAKE:-1}"
export AGENT_GREETING="${AGENT_GREETING:-Hello, this is Sarah from AFS, how can I help?}"
export GET_CASE_STATUS_FAST_EXTRACTOR="${GET_CASE_STATUS_FAST_EXTRACTOR:-1}"
export GET_CASE_STATUS_GEMINI_CLASSIFICATION="${GET_CASE_STATUS_GEMINI_CLASSIFICATION:-0}"
export GET_CASE_STATUS_GEMINI_EXTRACTION="${GET_CASE_STATUS_GEMINI_EXTRACTION:-0}"
export GET_CASE_STATUS_GEMINI_CORRECTIONS="${GET_CASE_STATUS_GEMINI_CORRECTIONS:-0}"

BACKEND_STDOUT_LOG="${RUN_DIR}/backend.stdout.log"

echo "Starting backend..."
"${ROOT}/.venv/bin/python" -m uvicorn api_server.server.fastapi_app:app \
  --host 127.0.0.1 --port 8000 \
  >"$BACKEND_STDOUT_LOG" 2>&1 &
BACKEND_PID=$!

cleanup() {
  if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Waiting for backend to be healthy..."
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo ""
echo "Local run dir: $RUN_DIR"
echo "Artifacts:"
echo "  - $RUN_DIR/backend.log.jsonl"
echo "  - $RUN_DIR/backend.tools.jsonl"
echo "  - $RUN_DIR/session-reports/"
echo "  - $RUN_DIR/agent.log.jsonl"
echo "  - $RUN_DIR/backend.stdout.log"
echo ""

echo "Starting agent console (audio). Press Ctrl+C to stop."
"${ROOT}/.venv/bin/python" -m livekit_agent.agent console --record
