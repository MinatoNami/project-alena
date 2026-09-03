# Voice Assistant Backend

FastAPI WebSocket backend for audio → text-whisperer (STT) → LM Studio or the
ALENA controller.

No model runs in this process. Audio is forwarded to
[text-whisperer](https://github.com/MinatoNami/text-whisperer) over the tailnet,
which is why there is no CUDA, PyTorch, numpy, scipy or librosa here any more.
See [../../../Documents/TEXT_WHISPERER_CONTRACT.md](../../../Documents/TEXT_WHISPERER_CONTRACT.md).

## Structure

Matches the requested layout under `backend/app/`.

## Run

From `modules/voice-assistant/backend`:

```bash
./scripts/start_server.sh
```

That creates the venv, installs dependencies, puts the repo root on
`PYTHONPATH` (the app imports `modules/llm` and `modules/stt` from there) and
starts uvicorn — with TLS if `certs/` holds a cert, without it otherwise.

By hand:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=../../.. uvicorn app.main:app --reload --port 8001
```

Configuration is read from the repo root `.env` (see `.env.example`).

Health check:

- `GET http://localhost:8001/health`

It reports the configured text-whisperer URL and whether it currently answers,
which is the first thing to check when voice input goes quiet.

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

- `LOG_LEVEL` (default `INFO`)
- `MAX_AUDIO_BYTES` (default `25000000`)
- `TEXT_WHISPERER_URL` (default `http://macbook-pro-14-m4-pro:8090`)
- `TEXT_WHISPERER_TOKEN` (text-whisperer's `WEB_PASSWORD`)
- `TEXT_WHISPERER_TIMEOUT` (default `300`)
- `TEXT_WHISPERER_LANGUAGE` (blank = auto-detect)
- `LLM_ENABLED` (default `true`)
- `LLM_BASE_URL` (default `http://localhost:1234`)
- `LLM_MODEL` (blank = whichever model LM Studio has loaded)
- `LLM_ROUTE` (default `alena`; `lmstudio` bypasses the controller and its tools)
- `ALENA_CONTROLLER_URL` (default `http://localhost:9000`)
- `ALENA_CONTROLLER_TIMEOUT` (default `120`)

## HTTP endpoints

Both proxy LM Studio so the browser never has to reach it directly:

- `GET /v1/models`
- `POST /v1/chat/completions` (server-sent events when `stream` is true)
