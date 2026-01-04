#!/usr/bin/env bash
set -euo pipefail

# Runs from anywhere; cd to this script's directory (backend/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
RELOAD="${RELOAD:-1}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements.txt

CERT_FILE="${CERT_FILE:-certs/10.8.0.1+1.pem}"
KEY_FILE="${KEY_FILE:-certs/10.8.0.1+1-key.pem}"

UVICORN_ARGS=("app.main:app" "--host" "$HOST" "--port" "$PORT" "--ssl-certfile" "$CERT_FILE" "--ssl-keyfile" "$KEY_FILE")
if [[ "$RELOAD" == "1" ]]; then
  UVICORN_ARGS+=("--reload")
fi

exec uvicorn "${UVICORN_ARGS[@]}"
