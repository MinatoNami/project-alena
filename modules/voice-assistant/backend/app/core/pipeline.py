from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import Settings
from app.services.llm.lmstudio import LMStudioClient
from app.services.llm.alena import AlenaClient
from app.services.stt.remote import RemoteSTT
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stt = RemoteSTT(settings=settings)
        self.lmstudio: Optional[LMStudioClient] = None
        self.alena: Optional[AlenaClient] = None
        route = (settings.llm_route or "alena").lower()
        self.llm_route = route

        if route == "lmstudio" and settings.llm_enabled:
            self.lmstudio = LMStudioClient(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_s=settings.llm_timeout,
            )
        elif route == "alena":
            self.alena = AlenaClient(
                base_url=settings.alena_controller_url,
                timeout_s=settings.alena_controller_timeout,
            )

    async def run(
        self, audio_bytes: bytes, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info("Pipeline: transcribing %d bytes of audio", len(audio_bytes))
        transcript = await self.stt.transcribe(audio_bytes, filename)
        transcript_text = transcript.get("text", "").strip()
        logger.info("Pipeline: transcription complete: %s", transcript_text)

        if not transcript_text:
            logger.warning("Pipeline: empty transcript, skipping LLM")
            return {"transcript": "", "llm_enabled": False, "prompt": ""}

        return {
            "transcript": transcript_text,
            "llm_enabled": (
                self.llm_route == "alena"
                or (self.llm_route == "lmstudio" and self.settings.llm_enabled)
            ),
            "prompt": transcript_text,
        }
