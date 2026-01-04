from __future__ import annotations

import io
from typing import Any, Dict, Optional

import numpy as np

from app.config import Settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def load_audio_from_wav_bytes(wav_bytes: bytes) -> np.ndarray:
    """Load audio from any audio format and return as numpy array."""
    try:
        from scipy.io import wavfile  # type: ignore
        from app.services.stt.audio import (
            is_wav_bytes,
            is_webm_bytes,
            webm_to_wav,
            raw_pcm_to_wav,
        )

        logger.debug("Loading audio: input size=%d bytes", len(wav_bytes))

        # Convert to WAV if needed
        if is_webm_bytes(wav_bytes):
            logger.debug("Detected webm format, converting to WAV")
            wav_bytes = webm_to_wav(wav_bytes)
            logger.debug("After webm conversion: %d bytes", len(wav_bytes))
        elif not is_wav_bytes(wav_bytes):
            logger.debug("Detected raw PCM, converting to WAV")
            wav_bytes = raw_pcm_to_wav(wav_bytes)
            logger.debug("After PCM conversion: %d bytes", len(wav_bytes))

        # Read WAV file from bytes
        sample_rate, audio_data = wavfile.read(io.BytesIO(wav_bytes))
        logger.debug(
            "Loaded audio: sample_rate=%d, shape=%s, dtype=%s, min=%f, max=%f",
            sample_rate,
            audio_data.shape,
            audio_data.dtype,
            float(np.min(audio_data)),
            float(np.max(audio_data)),
        )

        # Convert to float32 and normalize if needed
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            audio_data = audio_data.astype(np.float32) / 2147483648.0
        elif audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        logger.debug(
            "After normalization: min=%f, max=%f, mean=%f",
            float(np.min(audio_data)),
            float(np.max(audio_data)),
            float(np.mean(audio_data)),
        )

        # Resample to 16kHz if needed (Whisper standard)
        if sample_rate != 16000:
            try:
                import librosa  # type: ignore

                logger.info("Resampling from %d Hz to 16000 Hz", sample_rate)
                audio_data = librosa.resample(
                    audio_data, orig_sr=sample_rate, target_sr=16000
                )
            except ImportError:
                logger.warning(
                    "librosa not available; using audio at original sample rate %d Hz",
                    sample_rate,
                )

        # Validate audio quality
        audio_duration = len(audio_data) / 16000.0  # duration in seconds at 16kHz
        audio_rms = float(np.sqrt(np.mean(audio_data**2)))

        logger.info("Audio stats: duration=%.2fs, rms=%.4f", audio_duration, audio_rms)

        # Warn if audio is too quiet or too short
        if audio_rms < 0.001:
            logger.warning(
                "Audio RMS is very low (%.6f) - may be too quiet or silent", audio_rms
            )

        if audio_duration < 0.1:
            logger.warning("Audio duration is very short (%.2fs)", audio_duration)

        return audio_data
    except Exception as exc:
        logger.error("Failed to load audio from bytes: %s", exc)
        raise


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

        # Load audio directly from WAV bytes instead of using file path
        audio_data = load_audio_from_wav_bytes(audio_wav_bytes)

        if self._backend == "faster-whisper":
            segments, info = self._model.transcribe(audio_data)
            text_parts = []
            for seg in segments:
                if getattr(seg, "text", None):
                    text_parts.append(seg.text)
            text = "".join(text_parts).strip()
            result = {
                "backend": self._backend,
                "language": getattr(info, "language", None),
                "text": text,
            }
            logger.info(
                "Transcribed audio via %s (lang: %s, audio_size: %d bytes): %s",
                self._backend,
                result["language"],
                len(audio_wav_bytes),
                text,
            )
            return result

        # openai-whisper
        result = self._model.transcribe(audio_data)
        text = (result.get("text") or "").strip()
        logger.info(
            "Transcribed audio via %s (lang: %s, audio_size: %d bytes): %s",
            self._backend,
            result.get("language"),
            len(audio_wav_bytes),
            text,
        )
        return {
            "backend": self._backend,
            "language": result.get("language"),
            "text": text,
        }
