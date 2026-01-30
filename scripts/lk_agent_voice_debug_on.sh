#!/usr/bin/env bash
set -euo pipefail

# Big picture: enable repo-native, structured voice/turn logs at INFO level.
# PII is masked by default; set LOG_PII=1 only for short reproductions.

AGENT_ID="${1:-${LIVEKIT_AGENT_ID:-}}"
if [[ -z "${AGENT_ID}" ]]; then
  echo "usage: LIVEKIT_AGENT_ID=<id> $0 [agent_id]" >&2
  exit 2
fi

lk agent update-secrets --id "${AGENT_ID}" \
  --secrets "VOICE_DEBUG=1"

echo "enabled: VOICE_DEBUG=1 (agent restart triggered)"

