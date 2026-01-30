#!/usr/bin/env bash
set -euo pipefail

# Big picture: turn on *very* noisy OpenAI Realtime websocket debug logs for a short window.
# Use with care: treat logs as PII-bearing, and remember to turn it off after reproducing.

AGENT_ID="${1:-${LIVEKIT_AGENT_ID:-}}"
if [[ -z "${AGENT_ID}" ]]; then
  echo "usage: LIVEKIT_AGENT_ID=<id> $0 [agent_id]" >&2
  exit 2
fi

lk agent update-secrets --id "${AGENT_ID}" \
  --secrets "LK_OPENAI_DEBUG=1" \
  --secrets "LOG_LEVEL=DEBUG"

echo "enabled: LK_OPENAI_DEBUG=1 LOG_LEVEL=DEBUG (agent restart triggered)"

