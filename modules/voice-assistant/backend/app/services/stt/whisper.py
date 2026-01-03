from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import Settings
from app.services.stt.audio import write_wav_bytes_to_tempfile
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WhisperSTT:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._backend: Optional[str] = None
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        # Prefer faster-whisper if installed
        try:
            from faster_whisper import WhisperModel  # type: ignore

            self._backend = "faster-whisper"
            self._model = WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
            logger.info(
                "Loaded %s model via %s", self.settings.whisper_model, self._backend
            )
            return
        except Exception as exc:
            logger.warning(
                "faster-whisper unavailable (%s); falling back to openai-whisper", exc
            )

        # Fallback to openai-whisper
        import whisper  # type: ignore

        self._backend = "openai-whisper"
        self._model = whisper.load_model(self.settings.whisper_model)
        logger.info(
            "Loaded %s model via %s", self.settings.whisper_model, self._backend
        )

    async def transcribe_wav_bytes(self, audio_wav_bytes: bytes) -> Dict[str, Any]:
        self._ensure_model()
        path = write_wav_bytes_to_tempfile(audio_wav_bytes)

        if self._backend == "faster-whisper":
            segments, info = self._model.transcribe(str(path))
            text_parts = []
            for seg in segments:
                if getattr(seg, "text", None):
                    text_parts.append(seg.text)
            return {
                "backend": self._backend,
                "language": getattr(info, "language", None),
                "text": "".join(text_parts).strip(),
            }

        # openai-whisper
        result = self._model.transcribe(str(path))
        return {
            "backend": self._backend,
            "language": result.get("language"),
            "text": (result.get("text") or "").strip(),
        }
