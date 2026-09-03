from __future__ import annotations

import json

import httpx
import pytest

from modules.stt import (
    STTError,
    STTUnavailable,
    TextWhispererClient,
    TextWhispererConfig,
    sniff_extension,
)


def _client(handler, **config_kwargs) -> TextWhispererClient:
    config = TextWhispererConfig(base_url="http://whisper.test:8090", **config_kwargs)
    return TextWhispererClient(config, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_transcribe_returns_text_and_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/transcribe"
        assert b"audio.ogg" in request.content
        return httpx.Response(
            200,
            json={
                "text": "  hello there  ",
                "language": "en",
                "audio_seconds": 12.5,
                "elapsed_seconds": 0.5,
                "segments": [{"start": 0.0, "end": 1.0, "text": "hello there"}],
            },
        )

    result = await _client(handler).transcribe(b"OggS fake audio", "audio.ogg")

    assert result.text == "hello there"
    assert result.language == "en"
    assert result.audio_seconds == 12.5
    assert result.speed_factor == 25.0
    assert len(result.segments) == 1


@pytest.mark.asyncio
async def test_token_is_sent_as_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"text": "ok"})

    await _client(handler, api_token="s3cret").transcribe(b"OggS x", "a.ogg")
    assert seen["auth"] == "Bearer s3cret"


@pytest.mark.asyncio
async def test_language_is_forwarded_when_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="language"' in request.content
        assert b"en" in request.content
        return httpx.Response(200, json={"text": "ok"})

    await _client(handler, language="en").transcribe(b"OggS x", "a.ogg")


@pytest.mark.asyncio
async def test_unreachable_server_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(STTUnavailable):
        await _client(handler).transcribe(b"OggS x", "a.ogg")


@pytest.mark.asyncio
async def test_busy_server_is_unavailable_not_a_hard_error():
    handler = lambda request: httpx.Response(503, text="no model loaded")
    with pytest.raises(STTUnavailable):
        await _client(handler).transcribe(b"OggS x", "a.ogg")


@pytest.mark.asyncio
async def test_bad_credentials_raise_a_clear_error():
    handler = lambda request: httpx.Response(401, text="nope")
    with pytest.raises(STTError, match="credentials"):
        await _client(handler).transcribe(b"OggS x", "a.ogg")


@pytest.mark.asyncio
async def test_non_json_body_is_reported():
    handler = lambda request: httpx.Response(200, text="<html>login</html>")
    with pytest.raises(STTError, match="non-JSON"):
        await _client(handler).transcribe(b"OggS x", "a.ogg")


@pytest.mark.asyncio
async def test_empty_audio_is_rejected_before_the_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not have made a request")

    with pytest.raises(STTError, match="no audio"):
        await _client(handler).transcribe(b"")


@pytest.mark.asyncio
async def test_healthy_reports_reachability():
    assert await _client(lambda r: httpx.Response(200, json={})).healthy() is True

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert await _client(down).healthy() is False


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"OggS\x00\x02\x00\x00", "ogg"),
        (b"\x1aE\xdf\xa3\x01\x00\x00", "webm"),
        (b"\x00\x00\x00\x20ftypM4A ", "m4a"),
        (b"ID3\x04\x00", "mp3"),
        (b"random bytes here", "bin"),
    ],
)
def test_sniff_extension(data, expected):
    assert sniff_extension(data) == expected


@pytest.mark.asyncio
async def test_filename_is_derived_from_content_when_absent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "ok"})

    await _client(handler).transcribe(b"OggS\x00\x02 voice memo")
    assert b"audio.ogg" in seen["body"]
