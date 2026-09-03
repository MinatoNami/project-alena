from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from modules.stt import (
    STTError,
    STTUnavailable,
    TextWhispererClient,
    TextWhispererConfig,
)

from .config import TelegramBotConfig, load_config

LOGGER = logging.getLogger(__name__)


class TelegramWhisperBot:
    def __init__(self, config: TelegramBotConfig):
        self.config = config
        self._controller_semaphore = asyncio.Semaphore(
            self.config.controller_max_concurrency
        )

        self._stt: Optional[TextWhispererClient] = None
        if config.stt_url:
            self._stt = TextWhispererClient(
                TextWhispererConfig(
                    base_url=config.stt_url,
                    api_token=config.stt_token,
                    timeout_s=config.stt_timeout,
                    language=config.stt_language,
                    verify_ssl=config.stt_ssl_verify,
                )
            )
        else:
            LOGGER.warning(
                "TEXT_WHISPERER_URL is not set; voice messages cannot be transcribed."
            )

    def _should_forward(self, chat_id: int) -> bool:
        if chat_id == self.config.target_chat_id and not self.config.echo_in_target:
            return False

        if self.config.source_chat_ids is None:
            return True

        return chat_id in self.config.source_chat_ids

    def _format_sender(self, update: Update) -> str:
        chat = update.effective_chat
        user = update.effective_user
        parts = []
        if chat:
            if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
                parts.append(f"{chat.title} (group)")
            elif chat.type == ChatType.PRIVATE:
                parts.append("private")
            else:
                parts.append(chat.type)

        if user:
            name = " ".join(filter(None, [user.first_name, user.last_name]))
            handle = f"@{user.username}" if user.username else ""
            parts.append(" ".join(filter(None, [name, handle])).strip())

        return " | ".join([p for p in parts if p]) or "unknown"

    async def _forward_payload(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        source_chat_id: int,
        source_chat_type: Optional[str],
        source_user_id: Optional[int],
        payload: str,
    ) -> None:
        sent_to_target = False
        if self.config.target_chat_id != source_chat_id:
            await context.bot.send_message(
                chat_id=self.config.target_chat_id,
                text=payload,
            )
            sent_to_target = True

        if not sent_to_target and source_chat_type in {"group", "supergroup"}:
            if source_user_id is not None:
                await context.bot.send_message(
                    chat_id=source_user_id,
                    text=payload,
                )

        if self.config.reply_in_source and source_chat_id != self.config.target_chat_id:
            await context.bot.send_message(
                chat_id=source_chat_id,
                text=payload,
            )

    async def _call_controller(self, prompt: str, session_id: Optional[str]) -> str:
        if not self.config.controller_enabled:
            return ""

        base_url = self.config.controller_url.rstrip("/")
        if not base_url:
            return ""

        url = f"{base_url}/generate"
        payload = {"prompt": prompt}
        if session_id:
            payload["session_id"] = session_id

        try:
            async with self._controller_semaphore:
                timeout = httpx.Timeout(self.config.controller_timeout)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, dict):
                        return str(data.get("response") or "")
        except Exception as exc:
            LOGGER.exception("Controller request failed")
            return f"Controller error: {exc}"

        return ""

    async def _transcribe(self, audio: bytes, filename: str) -> str:
        """Transcribe a voice memo on text-whisperer.

        The bytes go up exactly as Telegram sent them: text-whisperer decodes
        with ffmpeg, so converting ogg/opus to WAV here would only be work done
        twice, and it is why this module no longer needs librosa or scipy.
        """
        if self._stt is None:
            raise STTUnavailable("TEXT_WHISPERER_URL is not configured")

        transcript = await self._stt.transcribe(audio, filename)
        LOGGER.info(
            "Transcribed %.1fs of audio in %.1fs (lang: %s)",
            transcript.audio_seconds,
            transcript.elapsed_seconds,
            transcript.language,
        )
        return transcript.text.strip()

    async def handle_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if not message or not message.text:
            return

        if message.from_user and message.from_user.is_bot:
            return

        if not self._should_forward(message.chat_id):
            return

        sender = self._format_sender(update)
        LOGGER.info(
            "Text message received | chat_id=%s | sender=%s | message_id=%s",
            message.chat_id,
            sender,
            message.message_id,
        )
        payload = f"{sender}: {message.text}"
        await self._forward_payload(
            context,
            message.chat_id,
            update.effective_chat.type if update.effective_chat else None,
            update.effective_user.id if update.effective_user else None,
            payload,
        )

        session_id = str(message.chat_id)
        controller_response = await self._call_controller(
            prompt=message.text,
            session_id=session_id,
        )
        if controller_response:
            await context.bot.send_message(
                chat_id=message.chat_id,
                text=controller_response,
                reply_to_message_id=message.message_id,
            )

    async def handle_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if not message or not message.voice:
            return

        if message.from_user and message.from_user.is_bot:
            return

        if not self._should_forward(message.chat_id):
            return

        sender = self._format_sender(update)
        LOGGER.info(
            "Voice message received | chat_id=%s | sender=%s | message_id=%s | duration=%ss",
            message.chat_id,
            sender,
            message.message_id,
            message.voice.duration,
        )

        if self._stt is None:
            await context.bot.send_message(
                chat_id=self.config.target_chat_id,
                text=(
                    "Transcription is not configured; set TEXT_WHISPERER_URL "
                    "to reach text-whisperer."
                ),
            )
            return

        voice_file = await context.bot.get_file(message.voice.file_id)
        # Telegram voice memos are ogg/opus; send them on untouched.
        audio = bytes(await voice_file.download_as_bytearray())

        try:
            text = await self._transcribe(audio, f"voice-{message.message_id}.ogg")
        except STTUnavailable as exc:
            # Retryable: the Mac is asleep or off the tailnet. Say so plainly
            # rather than making it look like the recording was bad.
            LOGGER.warning("text-whisperer unreachable: %s", exc)
            await context.bot.send_message(
                chat_id=self.config.target_chat_id,
                text=f"Transcription service is unreachable right now: {exc}",
            )
            return
        except STTError as exc:
            LOGGER.exception("Voice transcription failed")
            await context.bot.send_message(
                chat_id=self.config.target_chat_id,
                text=f"Voice transcription failed: {exc}",
            )
            return

        if text:
            payload = f"{sender}: {text}"
        else:
            payload = f"{sender}: (no speech detected)"

        await self._forward_payload(
            context,
            message.chat_id,
            update.effective_chat.type if update.effective_chat else None,
            update.effective_user.id if update.effective_user else None,
            payload,
        )

        if text:
            session_id = str(message.chat_id)
            controller_response = await self._call_controller(
                prompt=text,
                session_id=session_id,
            )
            if controller_response:
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=controller_response,
                    reply_to_message_id=message.message_id,
                )

    async def run(self) -> None:
        application = ApplicationBuilder().token(self.config.token).build()
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

        await application.initialize()
        await application.start()
        LOGGER.info("Telegram bot started")

        if application.updater is not None:
            await application.updater.start_polling()
            if hasattr(application.updater, "wait_for_stop"):
                await application.updater.wait_for_stop()
            elif hasattr(application.updater, "idle"):
                await application.updater.idle()
            else:
                await asyncio.Event().wait()
        else:
            await asyncio.Event().wait()

        await application.stop()
        await application.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()
    bot = TelegramWhisperBot(config)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
