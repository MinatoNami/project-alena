from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import Settings
from app.services.llm.ollama import OllamaClient
from app.services.stt.whisper import WhisperSTT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stt = WhisperSTT(settings=settings)
        self.ollama: Optional[OllamaClient] = None
        if settings.ollama_enabled:
            self.ollama = OllamaClient(
                base_url=settings.ollama_base_url, model=settings.ollama_model
            )

    async def run(self, audio_wav_bytes: bytes) -> Dict[str, Any]:
        logger.info("Pipeline: Starting transcription with %d bytes of audio", len(audio_wav_bytes))
        transcript = await self.stt.transcribe_wav_bytes(audio_wav_bytes)
        transcript_text = transcript.get("text", "").strip()
        logger.info("Pipeline: Transcription complete: %s", transcript_text)

        prompt = transcript_text
        if not prompt:
            logger.warning("Pipeline: Empty transcript, skipping LLM")
            return {"transcript": "", "llm_enabled": False, "prompt": ""}

        return {
            "transcript": transcript_text,
            "llm_enabled": bool(self.settings.ollama_enabled),
            "prompt": prompt,
        }
