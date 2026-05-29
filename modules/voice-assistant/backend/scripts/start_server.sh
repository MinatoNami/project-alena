#!/usr/bin/env bash
set -euo pipefail

# Runs from anywhere; cd to this script's directory (backend/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"
USE_SSL="${USE_SSL:-0}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements.txt

CERT_FILE="${CERT_FILE:-certs/server.pem}"
KEY_FILE="${KEY_FILE:-certs/server-key.pem}"

UVICORN_ARGS=("app.main:app" "--host" "$HOST" "--port" "$PORT")
if [[ "$USE_SSL" == "1" ]]; then
  UVICORN_ARGS+=("--ssl-certfile" "$CERT_FILE" "--ssl-keyfile" "$KEY_FILE")
fi
if [[ "$RELOAD" == "1" ]]; then
  UVICORN_ARGS+=("--reload")
fi

exec uvicorn "${UVICORN_ARGS[@]}"
