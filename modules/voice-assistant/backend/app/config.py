from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "voice-assistant-backend"
    log_level: str = "INFO"

    # WebSocket / audio
    max_audio_bytes: int = 25_000_000  # ~25MB safety limit

    # Speech-to-text: text-whisperer, over the tailnet. No model runs here.
    text_whisperer_url: str = "http://macbook-pro-14-m4-pro:8090"
    text_whisperer_token: str = ""
    text_whisperer_timeout: float = 300.0
    text_whisperer_language: str = ""
    text_whisperer_ssl_verify: bool = True

    # Inference: LM Studio, or anything else speaking the OpenAI API.
    llm_enabled: bool = True
    llm_base_url: str = "http://localhost:1234"
    llm_model: str = ""  # blank = whichever model LM Studio has loaded
    llm_timeout: float = 120.0

    # LLM routing
    llm_route: str = "alena"  # lmstudio|alena
    alena_controller_url: str = "http://localhost:9000"
    alena_controller_timeout: float = 120.0

    # CORS (useful if you connect from a browser)
    cors_allow_origins: List[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
