from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Set


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    target_chat_id: int
    source_chat_ids: Optional[Set[int]]
    echo_in_target: bool
    reply_in_source: bool


def _parse_int_set(value: str) -> Set[int]:
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def load_config() -> TelegramBotConfig:
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

    return TelegramBotConfig(
        token=token,
        target_chat_id=target_chat_id,
        source_chat_ids=source_chat_ids,
        echo_in_target=echo_in_target,
        reply_in_source=reply_in_source,
    )
