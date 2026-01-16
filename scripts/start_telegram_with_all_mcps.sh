#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_MCP_DIR="$ROOT_DIR/modules/mcp/codex-server"
GOOGLE_CALENDAR_MCP_DIR="$ROOT_DIR/modules/mcp/google-calendar"

kill_port_9000() {
  local pids
  pids=$(lsof -ti tcp:9000 2>/dev/null || true)
  if [[ -n "${pids}" ]]; then
    echo "Killing processes on port 9000: ${pids}"
    kill ${pids} 2>/dev/null || true
    sleep 1
    if lsof -ti tcp:9000 >/dev/null 2>&1; then
      echo "Force killing processes on port 9000"
      kill -9 ${pids} 2>/dev/null || true
    fi
  fi
}

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
  
  # Convert relative paths to absolute paths
  if [[ -n "${GOOGLE_CREDENTIALS_PATH:-}" && "${GOOGLE_CREDENTIALS_PATH}" != /* ]]; then
    export GOOGLE_CREDENTIALS_PATH="$ROOT_DIR/$GOOGLE_CREDENTIALS_PATH"
  fi
  if [[ -n "${GOOGLE_TOKEN_PATH:-}" && "${GOOGLE_TOKEN_PATH}" != /* ]]; then
    export GOOGLE_TOKEN_PATH="$ROOT_DIR/$GOOGLE_TOKEN_PATH"
  fi
fi

cleanup() {
  if [[ -n "${CODEX_MCP_PID:-}" ]]; then
    echo "Shutting down Codex MCP..."
    kill "$CODEX_MCP_PID" 2>/dev/null || true
  fi
  if [[ -n "${GOOGLE_CALENDAR_MCP_PID:-}" ]]; then
    echo "Shutting down Google Calendar MCP..."
    kill "$GOOGLE_CALENDAR_MCP_PID" 2>/dev/null || true
  fi
  if [[ -n "${CONTROLLER_PID:-}" ]]; then
    echo "Shutting down Controller..."
    kill "$CONTROLLER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

kill_port_9000

echo "Starting Codex MCP server..."
# Start Codex MCP server in background
(
  cd "$CODEX_MCP_DIR"
  python -m app.main
) &
CODEX_MCP_PID=$!
echo "Codex MCP server started with PID: $CODEX_MCP_PID"

echo "Starting Google Calendar MCP server..."
# Start Google Calendar MCP server in background
(
  cd "$GOOGLE_CALENDAR_MCP_DIR"
  export GOOGLE_CREDENTIALS_PATH
  export GOOGLE_TOKEN_PATH
  export CALENDAR_ID
  export CALENDAR_TIMEZONE
  python -m app.main
) &
GOOGLE_CALENDAR_MCP_PID=$!
echo "Google Calendar MCP server started with PID: $GOOGLE_CALENDAR_MCP_PID"

# Give MCP servers time to start
sleep 2

echo "Starting Controller..."
# Start Controller in background
(
  cd "$ROOT_DIR"
  python -m modules.core.server.main
) &
CONTROLLER_PID=$!
echo "Controller started with PID: $CONTROLLER_PID"

# Give Controller time to start
sleep 2

echo "Starting Telegram bot..."
# Launch Telegram bot (foreground)
cd "$ROOT_DIR"
python -m modules.telegram.bot
