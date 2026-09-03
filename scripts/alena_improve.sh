#!/usr/bin/env bash
# alena-improve wrapper.
#
# Exists so launchd and cron have something to call that does not depend on the
# working directory or on a shell that has already sourced .env.
#
#   scripts/alena_improve.sh scan --all
#   scripts/alena_improve.sh show project-alena
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

# Relative config paths in .env are relative to the repo, not to whatever
# directory a scheduler happened to start us in.
for var in ALENA_REPOSITORIES ALENA_TOOL_POLICY; do
  value="${!var:-}"
  if [[ -n "$value" && "$value" != /* && "$value" != "~"* ]]; then
    export "$var=$ROOT_DIR/$value"
  fi
done

# launchd starts a job with a bare PATH -- no login shell, no profile. Codex
# lives in ~/.local/bin for an npm global install, and a scheduled review that
# cannot find it fails at 22:30 on a Wednesday with nobody watching.
for dir in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
  if [[ -d "$dir" && ":$PATH:" != *":$dir:"* ]]; then
    PATH="$dir:$PATH"
  fi
done
export PATH

PYTHON="${ALENA_PYTHON:-python3}"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi

cd "$ROOT_DIR"
exec "$PYTHON" -m modules.improve "$@"
