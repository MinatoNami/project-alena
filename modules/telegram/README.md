# Telegram Whisper Bot

This module runs a Telegram bot that forwards incoming messages to a target group chat and transcribes voice messages using the existing Whisper STT module.

## Setup

1. Install dependencies:
   - Root dependencies: `pip install -r requirements.txt`
2. Create a Telegram bot using BotFather and get a token.
3. Add the bot to your group and disable privacy mode if you want it to receive all messages.
4. Set environment variables in the repo root `.env` (see `.env.example`):

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_TARGET_CHAT_ID=-1001234567890
# Optional: limit where the bot listens
# TELEGRAM_SOURCE_CHAT_IDS=123456789,-100987654321
# Optional: allow echo in target group
# TELEGRAM_ECHO_IN_TARGET=true
# Optional: reply back in source chat
# TELEGRAM_REPLY_IN_SOURCE=true
# Optional: pipe messages to controller and reply with response
# TELEGRAM_CONTROLLER_ENABLED=true
# TELEGRAM_CONTROLLER_URL=http://localhost:9000
# TELEGRAM_CONTROLLER_TIMEOUT=120
# TELEGRAM_CONTROLLER_MAX_CONCURRENCY=2
# TELEGRAM_STT_WS_URL=ws://whisper-host:8000/ws
# TELEGRAM_STT_TIMEOUT=60
# TELEGRAM_STT_SSL_VERIFY=true
```

5. Run the bot:

```
bash scripts/start_telegram_with_controller_mcp.sh
```

## Voice transcription

Telegram voice messages are OGG/Opus. The bot converts them to WAV before Whisper. Conversion uses `librosa` when available or falls back to `ffmpeg`. If `ffmpeg` is not installed, install it and ensure it is on your PATH.

For a remote Whisper server over WebSocket, set `TELEGRAM_STT_WS_URL` (e.g. `ws://whisper-host:8000/ws`). The bot will send WAV bytes using the same start/end protocol used by the voice assistant WebSocket. If you use `wss://` with a self-signed cert, set `TELEGRAM_STT_SSL_VERIFY=false`.

If you only use remote STT, you do not need local Whisper installed.
