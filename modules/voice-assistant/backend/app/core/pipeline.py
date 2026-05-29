from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, Optional

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
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_s=settings.ollama_timeout,
            )
        elif route == "alena":
            self.alena = AlenaClient(
                base_url=settings.alena_controller_url,
                timeout_s=settings.alena_controller_timeout,
            )

    async def transcribe(self, audio_bytes: bytes) -> Dict[str, Any]:
        logger.info(
            "Pipeline: Starting transcription with %d bytes of audio",
            len(audio_bytes),
        )
        transcript = await self.stt.transcribe_audio_bytes(audio_bytes)
        transcript_text = transcript.get("text", "").strip()
        logger.info("Pipeline: Transcription complete: %s", transcript_text)

        return {
            "transcript": transcript_text,
            "stt_backend": transcript.get("backend"),
            "language": transcript.get("language"),
            "prompt": transcript_text,
        }

    def can_generate(self) -> bool:
        return bool(self.llm_route == "ollama" and self.ollama is not None) or bool(
            self.llm_route == "alena" and self.alena is not None
        )

    def model_name(self) -> Optional[str]:
        if self.llm_route == "ollama" and self.ollama is not None:
            return self.ollama.model
        if self.llm_route == "alena" and self.alena is not None:
            return "alena-controller"
        return None

    async def stream_response(self, prompt: str) -> AsyncGenerator[str, None]:
        if not prompt:
            return

        if self.llm_route == "ollama" and self.ollama is not None:
            async for delta in self.ollama.stream_generate(prompt=prompt):
                yield delta
            return

        if self.llm_route == "alena" and self.alena is not None:
            text = await self.alena.generate(prompt=prompt)
            if text:
                yield text

    async def run(self, audio_bytes: bytes) -> Dict[str, Any]:
        transcription = await self.transcribe(audio_bytes)
        transcript_text = transcription.get("transcript", "").strip()
        prompt = transcript_text
        if not prompt:
            logger.warning("Pipeline: Empty transcript, skipping LLM")
            return {
                **transcription,
                "response": "",
                "llm_enabled": False,
                "model": None,
            }

        response = ""
        async for delta in self.stream_response(prompt):
            response += delta

        return {
            **transcription,
            "transcript": transcript_text,
            "response": response,
            "llm_enabled": self.can_generate(),
            "model": self.model_name(),
            "prompt": prompt,
        }
