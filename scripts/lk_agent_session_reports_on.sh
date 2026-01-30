#!/usr/bin/env bash
set -euo pipefail

# Big picture: publish LiveKit Agent SessionReports to the backend so we can fetch
# "last N calls" without tailing logs.
#
# This only sets the agent secrets. You still need the backend env var:
#   SESSION_REPORTS_TOKEN=<same token>  (optional but recommended)

AGENT_ID="${1:-${LIVEKIT_AGENT_ID:-}}"
REPORTS_URL="${2:-${SESSION_REPORTS_URL:-}}"
TOKEN="${SESSION_REPORTS_TOKEN:-}"

if [[ -z "${AGENT_ID}" ]]; then
  echo "usage: LIVEKIT_AGENT_ID=<id> SESSION_REPORTS_URL=<url> $0 [agent_id] [reports_url]" >&2
  exit 2
fi

if [[ -z "${REPORTS_URL}" ]]; then
  echo "error: missing reports URL (arg2 or SESSION_REPORTS_URL)" >&2
  exit 2
fi

cmd=(lk agent update-secrets --id "${AGENT_ID}" --secrets "SESSION_REPORTS_URL=${REPORTS_URL}")
if [[ -n "${TOKEN}" ]]; then
  cmd+=(--secrets "SESSION_REPORTS_TOKEN=${TOKEN}")
fi

"${cmd[@]}"

echo "enabled: SESSION_REPORTS_URL (and SESSION_REPORTS_TOKEN if provided) (agent restart triggered)"

