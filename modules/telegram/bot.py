from __future__ import annotations

import asyncio
import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx
import websockets
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from .config import TelegramBotConfig, load_config

LOGGER = logging.getLogger(__name__)

VOICE_ASSISTANT_BACKEND = (
    Path(__file__).resolve().parents[1] / "voice-assistant" / "backend"
)
if VOICE_ASSISTANT_BACKEND.exists():
    import sys

    if str(VOICE_ASSISTANT_BACKEND) not in sys.path:
        sys.path.insert(0, str(VOICE_ASSISTANT_BACKEND))

try:
    from app.config import Settings
    from app.services.stt.whisper import WhisperSTT
except Exception as exc:  # pragma: no cover - optional dependency path
    Settings = None  # type: ignore
    WhisperSTT = None  # type: ignore
    LOGGER.warning("Whisper backend unavailable: %s", exc)


def _is_wav_bytes(data: bytes) -> bool:
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def _ogg_to_wav_via_librosa(ogg_bytes: bytes) -> Optional[bytes]:
    tmp_path: Optional[str] = None
    try:
        import numpy as np
        from scipy.io import wavfile  # type: ignore
        import librosa  # type: ignore

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(ogg_bytes)
            tmp.flush()
            tmp_path = tmp.name

        audio_data, sample_rate = librosa.load(tmp_path, sr=None, mono=True)
        audio_int16 = (audio_data * 32767).astype(np.int16)
        wav_buffer = io.BytesIO()
        wavfile.write(wav_buffer, sample_rate, audio_int16)
        wav_buffer.seek(0)
        return wav_buffer.read()
    except Exception as exc:
        LOGGER.debug("librosa conversion failed: %s", exc)
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


def _ogg_to_wav_via_ffmpeg(ogg_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
        tmp_in.write(ogg_bytes)
        tmp_in.flush()
        input_path = tmp_in.name

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
        output_path = tmp_out.name

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                output_path,
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg conversion failed: {stderr}")

        return Path(output_path).read_bytes()
    finally:
        try:
            Path(input_path).unlink()
        except Exception:
            pass
        try:
            Path(output_path).unlink()
        except Exception:
            pass


def ogg_opus_to_wav_bytes(ogg_bytes: bytes) -> bytes:
    if _is_wav_bytes(ogg_bytes):
        return ogg_bytes

    wav_bytes = _ogg_to_wav_via_librosa(ogg_bytes)
    if wav_bytes is not None:
        return wav_bytes

    return _ogg_to_wav_via_ffmpeg(ogg_bytes)


class TelegramWhisperBot:
    def __init__(self, config: TelegramBotConfig):
        self.config = config
        self._stt = None
        self._controller_semaphore = asyncio.Semaphore(
            self.config.controller_max_concurrency
        )

        if WhisperSTT is not None and Settings is not None:
            settings = Settings()
            self._stt = WhisperSTT(settings)

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

    async def _transcribe_via_ws(self, audio_wav_bytes: bytes) -> str:
        if not self.config.stt_ws_url:
            return ""

        try:
            ssl_context = None
            if self.config.stt_ws_url.startswith("wss://"):
                import ssl

                if self.config.stt_ssl_verify:
                    ssl_context = ssl.create_default_context()
                else:
                    ssl_context = ssl._create_unverified_context()

            async with websockets.connect(
                self.config.stt_ws_url,
                max_size=25_000_000,
                open_timeout=self.config.stt_timeout,
                ssl=ssl_context,
            ) as ws:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=5)
                    if message:
                        LOGGER.debug("STT WS ready: %s", message)
                except Exception:
                    pass

                await ws.send('{"action":"start"}')
                await ws.send(audio_wav_bytes)
                await ws.send('{"action":"end"}')

                while True:
                    msg = await asyncio.wait_for(
                        ws.recv(), timeout=self.config.stt_timeout
                    )
                    if not msg:
                        continue
                    try:
                        import json

                        data = msg if isinstance(msg, str) else msg.decode("utf-8")
                        payload = json.loads(data)
                    except Exception:
                        continue

                    if isinstance(payload, dict) and payload.get("type") == "stt":
                        return str(payload.get("text") or "")
        except Exception as exc:
            LOGGER.exception("Remote STT websocket failed")
            return f""

        return ""

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
            if not self.config.stt_ws_url:
                await context.bot.send_message(
                    chat_id=self.config.target_chat_id,
                    text="Whisper backend not configured; cannot transcribe voice.",
                )
                return

        voice_file = await context.bot.get_file(message.voice.file_id)
        ogg_bytes = await voice_file.download_as_bytearray()

        try:
            wav_bytes = ogg_opus_to_wav_bytes(bytes(ogg_bytes))
            text = ""
            if self.config.stt_ws_url:
                text = (await self._transcribe_via_ws(wav_bytes)).strip()
            if not text and self._stt is not None:
                result = await self._stt.transcribe_wav_bytes(wav_bytes)
                text = (result.get("text") or "").strip()
        except Exception as exc:
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
