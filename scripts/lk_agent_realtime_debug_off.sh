#!/usr/bin/env bash
set -euo pipefail

AGENT_ID="${1:-${LIVEKIT_AGENT_ID:-}}"
if [[ -z "${AGENT_ID}" ]]; then
  echo "usage: LIVEKIT_AGENT_ID=<id> $0 [agent_id]" >&2
  exit 2
fi

lk agent update-secrets --id "${AGENT_ID}" \
  --secrets "LK_OPENAI_DEBUG=0" \
  --secrets "LOG_LEVEL=INFO"

echo "disabled: LK_OPENAI_DEBUG=0 LOG_LEVEL=INFO (agent restart triggered)"

