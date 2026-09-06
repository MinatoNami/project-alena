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
GOOGLE_CALENDAR_MCP_DIR="$ROOT_DIR/modules/mcp/google-calendar"

if [[ -f "$ROOT_DIR/.env" ]]; then
  # What the caller exported wins over the file: an empty line in
  # .env should not silently override it. See scripts/alena_improve.sh.
  _env_before="$(export -p)"
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
  eval "$_env_before"
  unset _env_before
  
  # Convert relative paths to absolute paths
  if [[ -n "${GOOGLE_CREDENTIALS_PATH:-}" && "${GOOGLE_CREDENTIALS_PATH}" != /* ]]; then
    export GOOGLE_CREDENTIALS_PATH="$ROOT_DIR/$GOOGLE_CREDENTIALS_PATH"
  fi
  if [[ -n "${GOOGLE_TOKEN_PATH:-}" && "${GOOGLE_TOKEN_PATH}" != /* ]]; then
    export GOOGLE_TOKEN_PATH="$ROOT_DIR/$GOOGLE_TOKEN_PATH"
  fi
fi

cleanup() {
  if [[ -n "${GOOGLE_CALENDAR_MCP_PID:-}" ]]; then
    echo "Stopping Google Calendar MCP server (PID: $GOOGLE_CALENDAR_MCP_PID)..."
    kill "$GOOGLE_CALENDAR_MCP_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

echo "Starting Google Calendar MCP server..."
# Start Google Calendar MCP server in background
# Export environment to subshell
(
  cd "$GOOGLE_CALENDAR_MCP_DIR"
  export GOOGLE_CREDENTIALS_PATH
  export GOOGLE_TOKEN_PATH
  export CALENDAR_ID
  export CALENDAR_TIMEZONE
  "$PYTHON" -m app.main
) &
GOOGLE_CALENDAR_MCP_PID=$!
echo "Google Calendar MCP server started with PID: $GOOGLE_CALENDAR_MCP_PID"

# Give MCP server time to start
sleep 2

echo "Starting ALENA..."
# Launch ALENA (foreground)
cd "$ROOT_DIR"
"$PYTHON" alena.py
