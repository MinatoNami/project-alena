#!/usr/bin/env bash
# The improvement dashboard: API on 9100, Nuxt on 3100.
#
# Both bind to loopback. The API can approve a recommendation, and an approved
# recommendation is what authorises the action agent to write to a repository,
# so the smallest exposure is the right default.
#
#   scripts/start_alena_dashboard.sh          # dev, with hot reload
#   scripts/start_alena_dashboard.sh --api    # just the API
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD_DIR="$ROOT_DIR/modules/improve/dashboard"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

PYTHON="${ALENA_PYTHON:-python3}"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi

cleanup() {
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT

cd "$ROOT_DIR"
echo "API       http://127.0.0.1:${ALENA_DASHBOARD_PORT:-9100}"

if [[ "${1:-}" == "--api" ]]; then
  exec "$PYTHON" -m modules.improve.web.api
fi

"$PYTHON" -m modules.improve.web.api &
API_PID=$!

if [[ ! -d "$DASHBOARD_DIR/node_modules" ]]; then
  echo "Installing dashboard dependencies..."
  (cd "$DASHBOARD_DIR" && npm install --no-fund --no-audit)
fi

echo "Dashboard http://127.0.0.1:3100"
cd "$DASHBOARD_DIR"
exec npm run dev
