#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

PUBLIC_HOST="${VOICE_ASSISTANT_PUBLIC_HOST:-localhost}"
BACKEND_HOST="${HOST:-0.0.0.0}"
BACKEND_PORT="${PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_MODE="${FRONTEND_MODE:-dev}"
SCHEME="${VOICE_ASSISTANT_SCHEME:-http}"
WS_SCHEME="ws"
if [[ "$SCHEME" == "https" ]]; then
  WS_SCHEME="wss"
fi

export HOST="$BACKEND_HOST"
export PORT="$BACKEND_PORT"
export NUXT_PUBLIC_LLM_API_URL="${NUXT_PUBLIC_LLM_API_URL:-$SCHEME://$PUBLIC_HOST:$BACKEND_PORT}"
export NUXT_PUBLIC_WS_AUDIO_URL="${NUXT_PUBLIC_WS_AUDIO_URL:-$WS_SCHEME://$PUBLIC_HOST:$BACKEND_PORT/ws}"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$SCRIPT_DIR/backend/scripts/start_server.sh" &
BACKEND_PID=$!

cd "$SCRIPT_DIR/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi

if [[ "$FRONTEND_MODE" == "preview" ]]; then
  npm run build
  NITRO_HOST="$FRONTEND_HOST" NITRO_PORT="$FRONTEND_PORT" \
    node .output/server/index.mjs &
else
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
fi
FRONTEND_PID=$!

echo "Voice backend: $SCHEME://$PUBLIC_HOST:$BACKEND_PORT"
echo "Voice frontend: http://$PUBLIC_HOST:$FRONTEND_PORT"
echo "Audio WebSocket: $NUXT_PUBLIC_WS_AUDIO_URL"

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
