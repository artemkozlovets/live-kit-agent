#!/usr/bin/env bash
set -euo pipefail

AGENT_ID="${1:-${LIVEKIT_AGENT_ID:-}}"
if [[ -z "${AGENT_ID}" ]]; then
  echo "usage: LIVEKIT_AGENT_ID=<id> $0 [agent_id]" >&2
  exit 2
fi

lk agent update-secrets --id "${AGENT_ID}" \
  --secrets "SESSION_REPORTS_URL=" \
  --secrets "SESSION_REPORTS_TOKEN="

echo "disabled: SESSION_REPORTS_URL/SESSION_REPORTS_TOKEN (agent restart triggered)"

