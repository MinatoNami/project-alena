from __future__ import annotations

import io
import tempfile
from pathlib import Path

import numpy as np


def is_wav_bytes(data: bytes) -> bool:
    # Minimal RIFF/WAVE sniffing
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def is_webm_bytes(data: bytes) -> bool:
    # Check for webm/mkv signature
    return len(data) >= 4 and data[0:4] == b"\x1aE\xdf\xa3"


def raw_pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, num_channels: int = 1) -> bytes:
    """Convert raw PCM audio to WAV format using scipy."""
    from scipy.io import wavfile  # type: ignore
    
    # Convert bytes to numpy array (assume 16-bit PCM)
    audio_array = np.frombuffer(pcm_data, dtype=np.int16)
    
    # If stereo, reshape accordingly
    if num_channels > 1:
        audio_array = audio_array.reshape(-1, num_channels)
    
    # Write to bytes buffer
    wav_buffer = io.BytesIO()
    wavfile.write(wav_buffer, sample_rate, audio_array)
    wav_buffer.seek(0)
    return wav_buffer.read()


def webm_to_wav(webm_data: bytes) -> bytes:
    """Convert webm/opus audio to WAV format."""
    from scipy.io import wavfile  # type: ignore
    import librosa  # type: ignore
    
    # Write webm data to temp file (librosa needs a file path for webm)
    tmp_webm = tempfile.NamedTemporaryFile(prefix="ws-audio-", suffix=".webm", delete=False)
    tmp_webm.write(webm_data)
    tmp_webm.flush()
    tmp_webm.close()
    
    try:
        # Load webm audio using librosa
        audio_data, sample_rate = librosa.load(tmp_webm.name, sr=None, mono=True)
        
        # Convert to int16
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        # Export as WAV
        wav_buffer = io.BytesIO()
        wavfile.write(wav_buffer, sample_rate, audio_int16)
        wav_buffer.seek(0)
        return wav_buffer.read()
    finally:
        # Clean up temp file
        try:
            Path(tmp_webm.name).unlink()
        except Exception:
            pass


def write_wav_bytes_to_tempfile(data: bytes) -> Path:
    # If data is already WAV, use as is
    if is_wav_bytes(data):
        wav_data = data
    elif is_webm_bytes(data):
        # Convert webm to WAV
        wav_data = webm_to_wav(data)
    else:
        # Assume raw PCM audio and convert to WAV
        wav_data = raw_pcm_to_wav(data)

    tmp = tempfile.NamedTemporaryFile(prefix="ws-audio-", suffix=".wav", delete=False)
    tmp.write(wav_data)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)
