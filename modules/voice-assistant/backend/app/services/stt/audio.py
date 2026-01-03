from __future__ import annotations

import tempfile
from pathlib import Path


def is_wav_bytes(data: bytes) -> bool:
    # Minimal RIFF/WAVE sniffing
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def write_wav_bytes_to_tempfile(data: bytes) -> Path:
    if not is_wav_bytes(data):
        raise ValueError("Expected WAV bytes (RIFF/WAVE)")

    tmp = tempfile.NamedTemporaryFile(prefix="ws-audio-", suffix=".wav", delete=False)
    tmp.write(data)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)
