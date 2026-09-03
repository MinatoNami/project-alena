# Telegram Bot

This module runs a Telegram bot that forwards incoming messages to a target group
chat, transcribes voice messages, and relays both to the ALENA controller.

Transcription happens on
[text-whisperer](https://github.com/MinatoNami/text-whisperer) over the tailnet.
No Whisper model, ffmpeg or audio library is needed here.

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
# Voice memos: where to transcribe them
TEXT_WHISPERER_URL=http://macbook-pro-14-m4-pro:8090
TEXT_WHISPERER_TOKEN=its_WEB_PASSWORD
# Optional: force a language (ISO code); blank auto-detects
# TEXT_WHISPERER_LANGUAGE=en
# Optional: a whole job, not a connect timeout
# TEXT_WHISPERER_TIMEOUT=300
# Optional: set false for a self-signed cert
# TEXT_WHISPERER_SSL_VERIFY=true
```

5. Run the bot:

```
bash scripts/start_telegram_with_controller_mcp.sh
```

## Voice transcription

Telegram voice memos are OGG/Opus, and are forwarded to text-whisperer exactly
as they arrive — it decodes with ffmpeg on its side. The bot does no audio
processing, so it needs neither ffmpeg nor librosa.

Set `TEXT_WHISPERER_URL` to reach it. Without it the bot still handles text and
says plainly that transcription is not configured when a voice memo arrives.

Two failures are reported differently on purpose: an unreachable server (the
Mac asleep, or off the tailnet) says so and is worth retrying, while a rejected
recording is reported as a failure of that message.

The endpoint it calls is described in
[../../Documents/TEXT_WHISPERER_CONTRACT.md](../../Documents/TEXT_WHISPERER_CONTRACT.md).
