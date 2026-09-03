"""Speech-to-text by handing audio to text-whisperer over the tailnet.

text-whisperer runs MLX Whisper on an Apple GPU, so transcription happens on
that machine and nothing here needs a model, CUDA, or an audio stack. It
decodes with ffmpeg on its side, so send the container bytes as they arrived —
ogg/opus from Telegram, webm from a browser — with no conversion first.

The endpoint this speaks to is documented in
Documents/TEXT_WHISPERER_CONTRACT.md. Transcription is a single request per
recording: mlx-whisper decodes a whole file in one pass and has no incremental
mode, so there is nothing a persistent connection would buy.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import httpx


class STTError(RuntimeError):
    pass


class STTUnavailable(STTError):
    """text-whisperer is unreachable — down, asleep, or off the tailnet."""


@dataclass(frozen=True)
class TextWhispererConfig:
    base_url: str = "http://macbook-pro-14-m4-pro:8090"
    # Shared secret for the transcribe endpoint. Empty is only safe while the
    # service is reachable on loopback or a tailnet.
    api_token: str = ""
    # Whisper is slower than realtime on long recordings; this is the ceiling
    # for a whole job, not a connect timeout.
    timeout_s: float = 300.0
    connect_timeout_s: float = 10.0
    verify_ssl: bool = True
    # Force a language (ISO code), or empty to let the server decide.
    language: str = ""

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def transcribe_url(self) -> str:
        return f"{self.normalized_base_url()}/api/transcribe"

    @property
    def status_url(self) -> str:
        return f"{self.normalized_base_url()}/api/status"


@dataclass
class Transcript:
    text: str
    language: Optional[str] = None
    audio_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    segments: tuple = field(default_factory=tuple)

    @property
    def speed_factor(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.audio_seconds / self.elapsed_seconds


# Enough for the server to pick a demuxer when the extension is unhelpful.
_CONTENT_TYPES = {
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/ogg",
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "flac": "audio/flac",
    "aac": "audio/aac",
}


def guess_content_type(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


def sniff_extension(data: bytes) -> str:
    """Name the container from its magic bytes.

    Callers often have bytes with no filename — a Telegram download, a
    WebSocket buffer. ffmpeg sniffs content anyway, but a truthful extension
    keeps the server's logs and archive readable.
    """
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if len(data) >= 4 and data[0:4] == b"OggS":
        return "ogg"
    if len(data) >= 4 and data[0:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    if len(data) >= 3 and data[0:3] == b"ID3":
        return "mp3"
    return "bin"


class TextWhispererClient:
    def __init__(
        self,
        config: TextWhispererConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.config = config
        # Tests pass an httpx.MockTransport here; nothing else should.
        self._transport = transport

    def _client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout,
            verify=self._verify(),
            transport=self._transport,
        )

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.config.timeout_s, connect=self.config.connect_timeout_s
        )

    def _verify(self):
        if self.config.verify_ssl:
            return True
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def _headers(self) -> Dict[str, str]:
        if self.config.api_token:
            return {"Authorization": f"Bearer {self.config.api_token}"}
        return {}

    def _request(self, audio: bytes, filename: Optional[str]) -> Tuple[dict, dict]:
        name = filename or f"audio.{sniff_extension(audio)}"
        files = {"audio": (name, audio, guess_content_type(name))}
        data: Dict[str, str] = {}
        if self.config.language:
            data["language"] = self.config.language
        return files, data

    async def transcribe(
        self, audio: bytes, filename: Optional[str] = None
    ) -> Transcript:
        """Send one recording and wait for its transcript."""
        if not audio:
            raise STTError("no audio to transcribe")

        files, data = self._request(audio, filename)

        try:
            async with self._client(self._timeout()) as client:
                response = await client.post(
                    self.config.transcribe_url,
                    files=files,
                    data=data,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise STTUnavailable(
                f"cannot reach text-whisperer at {self.config.normalized_base_url()}: {exc}"
            ) from exc

        return self._to_transcript(response)

    async def healthy(self) -> bool:
        try:
            async with self._client(
                httpx.Timeout(self.config.connect_timeout_s)
            ) as client:
                response = await client.get(
                    self.config.status_url, headers=self._headers()
                )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _to_transcript(response: httpx.Response) -> Transcript:
        if response.status_code == 401 or response.status_code == 403:
            raise STTError(
                "text-whisperer rejected the credentials "
                "(check TEXT_WHISPERER_TOKEN against its WEB_PASSWORD)"
            )
        # 503 is the server saying "busy or no model"; it is retryable, unlike
        # a 4xx, so it gets the unavailable type.
        if response.status_code == 503:
            raise STTUnavailable("text-whisperer is not ready to transcribe")
        if response.status_code >= 400:
            detail = response.text.strip()[:300] or response.reason_phrase
            raise STTError(f"text-whisperer returned {response.status_code}: {detail}")

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise STTError(f"text-whisperer returned a non-JSON body: {exc}") from exc

        if not isinstance(payload, dict):
            raise STTError("text-whisperer returned an unexpected body")

        if payload.get("error"):
            raise STTError(str(payload["error"]))

        return Transcript(
            text=str(payload.get("text") or "").strip(),
            language=payload.get("language"),
            audio_seconds=float(payload.get("audio_seconds") or 0.0),
            elapsed_seconds=float(payload.get("elapsed_seconds") or 0.0),
            segments=tuple(payload.get("segments") or ()),
        )
