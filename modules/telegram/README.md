# Telegram Whisper Bot

This module runs a Telegram bot that forwards incoming messages to a target group chat and transcribes voice messages using the existing Whisper STT module.

## Setup

1. Install dependencies:
   - Telegram bot runtime: `pip install -r modules/telegram/requirements.txt`
   - Whisper dependencies: `pip install -r modules/voice-assistant/backend/requirements.txt`
2. Create a Telegram bot using BotFather and get a token.
3. Add the bot to your group and disable privacy mode if you want it to receive all messages.
4. Set environment variables:

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_TARGET_CHAT_ID=-1001234567890
# Optional: limit where the bot listens
# TELEGRAM_SOURCE_CHAT_IDS=123456789,-100987654321
# Optional: allow echo in target group
# TELEGRAM_ECHO_IN_TARGET=true
# Optional: reply back in source chat
# TELEGRAM_REPLY_IN_SOURCE=true
```

5. Run the bot:

```
python -m modules.telegram.bot
```

## Voice transcription

Telegram voice messages are OGG/Opus. The bot converts them to WAV before Whisper. Conversion uses `librosa` when available or falls back to `ffmpeg`. If `ffmpeg` is not installed, install it and ensure it is on your PATH.
