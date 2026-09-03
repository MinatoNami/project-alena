"""Remote speech-to-text for Project ALENA (text-whisperer over the tailnet)."""

from .text_whisperer import (
    STTError,
    STTUnavailable,
    TextWhispererClient,
    TextWhispererConfig,
    Transcript,
    guess_content_type,
    sniff_extension,
)

__all__ = [
    "STTError",
    "STTUnavailable",
    "TextWhispererClient",
    "TextWhispererConfig",
    "Transcript",
    "guess_content_type",
    "sniff_extension",
]
