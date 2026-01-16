#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/modules/telegram/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/modules/telegram/.env"
  set +a
fi

bash "$ROOT_DIR/scripts/start_controller_with_mcp.sh" &
CONTROLLER_PID=$!

cleanup() {
  if kill -0 "$CONTROLLER_PID" >/dev/null 2>&1; then
    kill "$CONTROLLER_PID"
  fi
}
trap cleanup EXIT

python -m modules.telegram.bot
