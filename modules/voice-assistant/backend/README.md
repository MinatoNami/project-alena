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

uvicorn app.main:app --reload --port 8001
```

Or use the helper script:

```bash
chmod +x start_server.sh
./start_server.sh
```

Health check:

- `GET http://localhost:8001/health`

## WebSocket protocol

Endpoint:

- `ws://localhost:8001/ws`

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
- `WHISPER_MODEL` (default `small`)
- `WHISPER_DEVICE` (default `cpu`)
- `WHISPER_COMPUTE_TYPE` (default `int8`)
- `OLLAMA_ENABLED` (default `true`)
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `llama3.1`)
