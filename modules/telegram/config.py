from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"

from dataclasses import dataclass
from typing import Optional, Set


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    target_chat_id: int
    source_chat_ids: Optional[Set[int]]
    echo_in_target: bool
    reply_in_source: bool
    controller_enabled: bool
    controller_url: str
    controller_timeout: float
    controller_max_concurrency: int
    stt_ws_url: Optional[str]
    stt_timeout: float
    stt_ssl_verify: bool


def _parse_int_set(value: str) -> Set[int]:
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def load_config() -> TelegramBotConfig:
    if load_dotenv is not None:
        load_dotenv(_ROOT_ENV, override=False)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    target_chat_id_raw = os.getenv("TELEGRAM_TARGET_CHAT_ID", "").strip()
    if not target_chat_id_raw:
        raise ValueError("TELEGRAM_TARGET_CHAT_ID is required")

    target_chat_id = int(target_chat_id_raw)

    source_chat_ids_raw = os.getenv("TELEGRAM_SOURCE_CHAT_IDS", "").strip()
    source_chat_ids = (
        _parse_int_set(source_chat_ids_raw) if source_chat_ids_raw else None
    )

    echo_in_target = os.getenv("TELEGRAM_ECHO_IN_TARGET", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    reply_in_source = os.getenv("TELEGRAM_REPLY_IN_SOURCE", "false").lower() in {
        "1",
        "true",
        "yes",
    }

    controller_enabled = os.getenv("TELEGRAM_CONTROLLER_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    controller_url = os.getenv(
        "TELEGRAM_CONTROLLER_URL", "http://localhost:9000"
    ).strip()
    controller_timeout = float(os.getenv("TELEGRAM_CONTROLLER_TIMEOUT", "120"))
    controller_max_concurrency = int(
        os.getenv("TELEGRAM_CONTROLLER_MAX_CONCURRENCY", "2")
    )
    if controller_max_concurrency < 1:
        controller_max_concurrency = 1

    stt_ws_url = os.getenv("TELEGRAM_STT_WS_URL", "").strip() or None
    stt_timeout = float(os.getenv("TELEGRAM_STT_TIMEOUT", "60"))
    stt_ssl_verify = os.getenv("TELEGRAM_STT_SSL_VERIFY", "true").lower() in {
        "1",
        "true",
        "yes",
    }

    return TelegramBotConfig(
        token=token,
        target_chat_id=target_chat_id,
        source_chat_ids=source_chat_ids,
        echo_in_target=echo_in_target,
        reply_in_source=reply_in_source,
        controller_enabled=controller_enabled,
        controller_url=controller_url,
        controller_timeout=controller_timeout,
        controller_max_concurrency=controller_max_concurrency,
        stt_ws_url=stt_ws_url,
        stt_timeout=stt_timeout,
        stt_ssl_verify=stt_ssl_verify,
    )
