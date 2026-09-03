from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import Settings
from app.utils.logger import get_logger
from modules.stt import STTError, TextWhispererClient, TextWhispererConfig

logger = get_logger(__name__)


class RemoteSTT:
    """Transcription by text-whisperer.

    This used to load faster-whisper in-process, which is why the backend
    needed CUDA, numpy, scipy and librosa. It now forwards the bytes and keeps
    none of that: no model, no resampling, no format conversion.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = TextWhispererClient(
            TextWhispererConfig(
                base_url=settings.text_whisperer_url,
                api_token=settings.text_whisperer_token,
                timeout_s=settings.text_whisperer_timeout,
                language=settings.text_whisperer_language,
                verify_ssl=settings.text_whisperer_ssl_verify,
            )
        )

    async def transcribe(
        self, audio_bytes: bytes, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info("Sending %d bytes to text-whisperer", len(audio_bytes))
        transcript = await self._client.transcribe(audio_bytes, filename)
        logger.info(
            "Transcribed %.1fs of audio in %.1fs (lang: %s): %s",
            transcript.audio_seconds,
            transcript.elapsed_seconds,
            transcript.language,
            transcript.text,
        )
        return {
            "backend": "text-whisperer",
            "language": transcript.language,
            "text": transcript.text,
        }

    async def healthy(self) -> bool:
        return await self._client.healthy()


__all__ = ["RemoteSTT", "STTError"]
