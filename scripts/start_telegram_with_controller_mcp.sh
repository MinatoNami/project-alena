#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
fi

kill_port_9000

bash "$ROOT_DIR/scripts/start_controller_with_mcp.sh" &
CONTROLLER_PID=$!

cleanup() {
  if kill -0 "$CONTROLLER_PID" >/dev/null 2>&1; then
    kill "$CONTROLLER_PID"
  fi
}
trap cleanup EXIT

python -m modules.telegram.bot
