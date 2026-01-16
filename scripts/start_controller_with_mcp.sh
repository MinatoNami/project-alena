#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$ROOT_DIR/modules/mcp/codex-server"

cleanup() {
  if [[ -n "${MCP_PID:-}" ]]; then
    kill "$MCP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Start MCP server in background
(
  cd "$MCP_DIR"
  python -m app.main
) &
MCP_PID=$!

# Start ALENA controller server (foreground)
cd "$ROOT_DIR"
python -m modules.core.server.main
