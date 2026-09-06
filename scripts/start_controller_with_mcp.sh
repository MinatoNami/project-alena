#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The interpreter to use. `python` does not exist on macOS outside an activated
# virtualenv -- which is how a scheduled Codex review recorded
# `FileNotFoundError: [Errno 2] No such file or directory: 'python'` as its
# assessment. `alena_improve.sh` and the dashboard script already resolved
# this; these did not.
PYTHON="$ROOT_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3 || command -v python)"
MCP_DIR="$ROOT_DIR/modules/mcp/codex-server"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

cleanup() {
  if [[ -n "${MCP_PID:-}" ]]; then
    kill "$MCP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Start MCP server in background
(
  cd "$MCP_DIR"
  "$PYTHON" -m app.main
) &
MCP_PID=$!

# Start ALENA controller server (foreground)
cd "$ROOT_DIR"
"$PYTHON" -m modules.core.server.main
