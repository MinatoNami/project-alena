#!/usr/bin/env bash
set -euo pipefail

# Runs from anywhere. The app lives one level up from this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$BACKEND_DIR/../../.." && pwd)"
cd "$BACKEND_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

# The backend imports modules/llm and modules/stt from the repo root, so the
# root has to be importable even though uvicorn runs from this directory.
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
HOST="${HOST:-localhost}"
PORT="${PORT:-8001}"
RELOAD="${RELOAD:-1}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements.txt

UVICORN_ARGS=("app.main:app" "--host" "$HOST" "--port" "$PORT")

# TLS is optional: the browser needs it for getUserMedia over a non-localhost
# origin, but a loopback or tailnet-terminated setup does not.
CERT_FILE="${CERT_FILE:-certs/server.pem}"
KEY_FILE="${KEY_FILE:-certs/server-key.pem}"
if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
  UVICORN_ARGS+=("--ssl-certfile" "$CERT_FILE" "--ssl-keyfile" "$KEY_FILE")
else
  echo "No certs at $CERT_FILE / $KEY_FILE; starting without TLS." >&2
fi

if [[ "$RELOAD" == "1" ]]; then
  UVICORN_ARGS+=("--reload")
fi

exec uvicorn "${UVICORN_ARGS[@]}"
