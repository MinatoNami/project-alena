# Voice Assistant Backend

FastAPI WebSocket backend for audio → Whisper (STT) → Ollama (LLM).

## Structure

Matches the requested layout under `backend/app/`.

## Run

From `modules/voice-assistant/backend`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# install ONE of these STT backends:
# pip install faster-whisper
# or
# pip install openai-whisper

uvicorn app.main:app --reload --port 8000
```

Or use the helper script:

```bash
chmod +x start_server.sh
./start_server.sh
```

Configuration is read from the repo root `.env` (see `.env.example`).

Health check:

- `GET http://localhost:8000/health`

## SSL (local development)

This backend can be run over HTTPS/WSS by providing a certificate and key.

### Generate local `.pem` certs (mkcert)

The filenames in the run command below match mkcert's output naming.

1. Install mkcert (once):

- Windows (Chocolatey):

```powershell
choco install mkcert
mkcert -install
```

2. Generate the cert + key into `certs/`:

```powershell
cd modules/voice-assistant/backend
mkdir certs -Force
mkcert -cert-file certs/server.pem -key-file certs/server-key.pem localhost
```

Notes:

- `*.pem` is ignored via the repo root `.gitignore`.
- If you previously committed any `.pem` files, untrack them with:

```powershell
git rm --cached -r -- **/*.pem
```

### Run with SSL (PowerShell)

From `modules/voice-assistant/backend`:

```powershell
python -m uvicorn app.main:app `
  --host localhost `
  --port 8000 `
  --ssl-certfile certs/server.pem `
  --ssl-keyfile certs/server-key.pem
```

## WebSocket protocol

Endpoint:

- `ws://localhost:8000/ws`

Messages:

- Binary frames: raw WAV bytes (you can send multiple chunks)
- Text frames: JSON control messages

Control JSON:

- `{ "action": "start" }` resets the buffer
- `{ "action": "end" }` runs STT→LLM and streams results
- `{ "action": "ping" }`

Server responses (JSON):

- `{ "type": "ready" }`
- `{ "type": "audio", "event": "chunk", "bytes": 1234, "total": 5678 }`
- `{ "type": "stt", "text": "..." }`
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
- `LLM_ROUTE` (default `ollama`)
- `ALENA_CONTROLLER_URL` (default `http://localhost:9000`)
- `ALENA_CONTROLLER_TIMEOUT` (default `120`)
