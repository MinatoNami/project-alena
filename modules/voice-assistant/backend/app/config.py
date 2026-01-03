from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "voice-assistant-backend"
    log_level: str = "INFO"

    # WebSocket / audio
    max_audio_bytes: int = 25_000_000  # ~25MB safety limit

    # Whisper / faster-whisper
    whisper_model: str = "small"
    whisper_device: str = "cpu"  # cpu|cuda
    whisper_compute_type: str = "int8"  # faster-whisper compute type

    # Ollama
    ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # CORS (useful if you connect from a browser)
    cors_allow_origins: List[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
