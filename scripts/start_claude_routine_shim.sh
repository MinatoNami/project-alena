#!/usr/bin/env bash
# The local Claude routine endpoint, on loopback.
#
# ALENA's independent reviewer posts a prompt to CLAUDE_ROUTINE_URL and reads
# the answer. This serves that contract with the `claude` CLI already on the
# machine -- no API key, and no hosted trigger to arrange.
#
#   scripts/start_claude_routine_shim.sh
#   CLAUDE_ROUTINE_URL=http://127.0.0.1:9200/review alena-improve check-routine
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  _env_before="$(export -p)"
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
  eval "$_env_before"
  unset _env_before
fi

# launchd gives a job a bare PATH, and the CLI is usually installed by npm.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v claude >/dev/null 2>&1; then
  echo "The \`claude\` CLI is not on PATH; the shim has nothing to call." >&2
  exit 1
fi

cd "$ROOT_DIR"
PYTHON="$ROOT_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

echo "Routine  http://${CLAUDE_ROUTINE_HOST:-127.0.0.1}:${CLAUDE_ROUTINE_PORT:-9200}/review"
exec "$PYTHON" -m modules.improve.agents.routine_shim
