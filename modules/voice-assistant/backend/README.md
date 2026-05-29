# Voice Assistant Backend

FastAPI WebSocket backend for audio -> Whisper (STT) -> Ollama (LLM).

The backend can run independently on another device. In that deployment, this
service owns the WebSocket server and Whisper STT, then calls Ollama by URL and
returns the transcript and generated response over the same WebSocket.

## Structure

Matches the requested layout under `backend/app/`.

## Run Backend Only

From `modules/voice-assistant/backend`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# install ONE of these STT backends:
# pip install faster-whisper
# or
# pip install openai-whisper

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or use the helper script:

```bash
chmod +x scripts/start_server.sh
./scripts/start_server.sh
```

Configuration is read from the repo root `.env` (see `.env.example`).

Health check:

- `GET http://localhost:8000/health`

## Run Backend + Frontend on a Voice Device

From the repo root on the device that will host the voice assistant:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg nodejs npm

cp .env.example .env
```

Edit `.env`:

```env
HOST=0.0.0.0
PORT=8000
VOICE_ASSISTANT_PUBLIC_HOST=192.168.1.25

WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://192.168.1.50:11434
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_TIMEOUT=120
LLM_ROUTE=ollama
```

Use the voice device's LAN IP for `VOICE_ASSISTANT_PUBLIC_HOST`. Use the Ollama
machine's URL for `OLLAMA_BASE_URL`; if Ollama runs on the same device, use
`http://localhost:11434`.

Start both services:

```bash
./modules/voice-assistant/start_standalone.sh
```

For a production-built Nuxt server instead of the dev server:

```bash
FRONTEND_MODE=preview ./modules/voice-assistant/start_standalone.sh
```

Open the frontend from another machine:

```text
http://192.168.1.25:3000
```

The frontend will connect to:

```text
ws://192.168.1.25:8000/ws
```

If browser microphone access is blocked over plain HTTP, use localhost for
testing or run the backend/frontend behind HTTPS/WSS.

## Run Backend with Docker Compose on Ubuntu

The compose file reads configuration from the repo root `.env`, not from
`modules/voice-assistant/backend/.env`.

From the repo root:

```bash
cp .env.example .env
```

Edit `.env` for the voice device:

```env
HOST=0.0.0.0
PORT=8000
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
OLLAMA_BASE_URL=http://192.168.1.50:11434
OLLAMA_MODEL=gpt-oss:20b
LLM_ROUTE=ollama
```

Start the backend container:

```bash
cd modules/voice-assistant/backend
docker compose up --build
```

Health check:

```bash
curl http://localhost:8000/health
```

The backend WebSocket will be:

```text
ws://<voice-device-ip>:8000/ws
```

If you want GPU acceleration in Docker, install the NVIDIA Container Toolkit on
Ubuntu and keep `gpus: all` in `docker-compose.yml`. For CPU-only Docker, remove
or comment out `gpus: all` and use:

```env
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

## SSL / HTTPS on Ubuntu

This backend can be run over HTTPS/WSS by providing a certificate and key.
This is optional for the standalone setup, but it is useful when browsers block
microphone access over plain HTTP or when the frontend is served over HTTPS.

### Option 1: Plain HTTP for LAN Testing

Skip certs and run the backend with:

```bash
cd modules/voice-assistant/backend
HOST=0.0.0.0 PORT=8000 USE_SSL=0 ./scripts/start_server.sh
```

The frontend should use:

```env
NUXT_PUBLIC_WS_AUDIO_URL=ws://192.168.1.25:8000/ws
```

### Option 2: Generate Local Certs with mkcert

Install mkcert on Ubuntu:

```bash
sudo apt update
sudo apt install -y libnss3-tools wget
wget -O mkcert https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-v1.4.4-linux-amd64
chmod +x mkcert
sudo mv mkcert /usr/local/bin/
mkcert -install
```

Generate certs for localhost and your voice device LAN IP:

```bash
cd modules/voice-assistant/backend
mkdir -p certs
mkcert -cert-file certs/server.pem -key-file certs/server-key.pem localhost 127.0.0.1 192.168.1.25
```

Replace `192.168.1.25` with the voice device IP.

Run with SSL:

```bash
HOST=0.0.0.0 PORT=8000 USE_SSL=1 ./scripts/start_server.sh
```

The frontend should use:

```env
VOICE_ASSISTANT_SCHEME=https
NUXT_PUBLIC_WS_AUDIO_URL=wss://192.168.1.25:8000/ws
```

Trust note: mkcert installs a local CA on the machine where you run
`mkcert -install`. If you open the frontend from another laptop/phone, that
client may still not trust the cert until you install the mkcert root CA there
too. For a permanent LAN setup, use a trusted certificate through a reverse proxy
or serve the app from localhost on the device doing the recording.

### Certificate Files

- `*.pem` is ignored via the repo root `.gitignore`.
- Expected local files:
  - `modules/voice-assistant/backend/certs/server.pem`
  - `modules/voice-assistant/backend/certs/server-key.pem`
- If you previously committed any `.pem` files, untrack them with:

```bash
git rm --cached -r -- **/*.pem
```

## WebSocket protocol

Endpoint:

- `ws://localhost:8000/ws`

Messages:

- Binary frames: audio bytes. The browser frontend sends raw PCM16 chunks.
- Text frames: JSON control messages

Control JSON:

- `{ "action": "start" }` resets the buffer
- `{ "action": "end" }` runs STT→LLM and streams results
- `{ "action": "ping" }`

Server responses (JSON):

- `{ "type": "ready" }`
- `{ "type": "audio", "event": "chunk", "bytes": 1234, "total": 5678 }`
- `{ "type": "stt", "text": "...", "backend": "faster-whisper", "language": "en" }`
- LLM streaming:
  - `{ "type": "llm", "event": "start", "model": "...", "prompt": "..." }`
  - `{ "type": "llm", "delta": "..." }`
  - `{ "type": "llm", "event": "end", "text": "full answer" }`

## Environment variables

- `LOG_LEVEL` (default `DEBUG`)
- `MAX_AUDIO_BYTES` (default `25000000`)
- `WHISPER_MODEL` (default `small`)
- `WHISPER_DEVICE` (default `cpu`)
- `WHISPER_COMPUTE_TYPE` (default `int8`)
- `OLLAMA_ENABLED` (default `true`)
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `llama3.1`)
- `OLLAMA_TIMEOUT` (default `120`)
- `LLM_ROUTE` (default `ollama`)
- `ALENA_CONTROLLER_URL` (default `http://localhost:9000`)
- `ALENA_CONTROLLER_TIMEOUT` (default `120`)
