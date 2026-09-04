#!/usr/bin/env bash
# Run the alena-core MCP server on stdio.
#
# This is what an external client is pointed at. Claude Code, ChatGPT and a
# local model all reach the same implementation through it, which is the whole
# point of putting ALENA's capabilities behind MCP rather than behind three
# provider-specific integrations.
#
# Every tool it exposes is read-only. A client configured to reach this server
# talks to it directly, with ALENA's Tool Gateway nowhere in the path, so
# read-only by construction is what makes it safe to hand out.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

for var in ALENA_REPOSITORIES ALENA_TOOL_POLICY; do
  value="${!var:-}"
  if [[ -n "$value" && "$value" != /* && "$value" != "~"* ]]; then
    export "$var=$ROOT_DIR/$value"
  fi
done

PYTHON="${ALENA_PYTHON:-python3}"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi

cd "$ROOT_DIR/modules/mcp/alena-core"
exec "$PYTHON" -m app.main
