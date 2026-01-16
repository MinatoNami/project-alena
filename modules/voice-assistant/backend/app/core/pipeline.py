from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import Settings
from app.services.llm.ollama import OllamaClient
from app.services.llm.alena import AlenaClient
from app.services.stt.whisper import WhisperSTT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stt = WhisperSTT(settings=settings)
        self.ollama: Optional[OllamaClient] = None
        self.alena: Optional[AlenaClient] = None
        route = (settings.llm_route or "ollama").lower()
        self.llm_route = route

        if route == "ollama" and settings.ollama_enabled:
            self.ollama = OllamaClient(
                base_url=settings.ollama_base_url, model=settings.ollama_model
            )
        elif route == "alena":
            self.alena = AlenaClient(
                base_url=settings.alena_controller_url,
                timeout_s=settings.alena_controller_timeout,
            )

    async def run(self, audio_wav_bytes: bytes) -> Dict[str, Any]:
        logger.info(
            "Pipeline: Starting transcription with %d bytes of audio",
            len(audio_wav_bytes),
        )
        transcript = await self.stt.transcribe_wav_bytes(audio_wav_bytes)
        transcript_text = transcript.get("text", "").strip()
        logger.info("Pipeline: Transcription complete: %s", transcript_text)

        prompt = transcript_text
        if not prompt:
            logger.warning("Pipeline: Empty transcript, skipping LLM")
            return {"transcript": "", "llm_enabled": False, "prompt": ""}

        return {
            "transcript": transcript_text,
            "llm_enabled": bool(
                self.llm_route == "ollama" and self.settings.ollama_enabled
            )
            or bool(self.llm_route == "alena"),
            "prompt": prompt,
        }
