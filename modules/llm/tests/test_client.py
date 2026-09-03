from __future__ import annotations

import json

import httpx
import pytest

from modules.llm import (
    LLMAsyncClient,
    LLMChatClient,
    LLMConfig,
    LLMUnavailable,
    ReasoningFilter,
    extract_reply,
    strip_reasoning,
)


# --- reasoning removal ------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<think>hmm</think>Hello", "Hello"),
        ("<thinking>a</thinking>b", "b"),
        ("<REASONING>a</REASONING>b", "b"),
        ("no tags here", "no tags here"),
        # A reply truncated mid-thought never closes the tag.
        ("answer <think>cut off half way", "answer"),
        ("", ""),
    ],
)
def test_strip_reasoning(raw, expected):
    assert strip_reasoning(raw) == expected


def test_reasoning_filter_holds_state_across_chunks():
    f = ReasoningFilter()
    chunks = ["Hel", "lo <think>", "the secret", "</think> wor", "ld"]
    assert "".join(f.feed(c) for c in chunks) == "Hello  world"
    assert f.in_reasoning is False


def test_reasoning_filter_suppresses_an_unclosed_span():
    f = ReasoningFilter()
    assert "".join(f.feed(c) for c in ["<think>", "still going"]) == ""
    assert f.in_reasoning is True


# --- reply extraction -------------------------------------------------------


def _reply(message: dict) -> str:
    return extract_reply({"choices": [{"message": message}]})


def test_extract_plain_content():
    assert _reply({"content": "hello"}) == "hello"


def test_extract_strips_reasoning_from_content():
    assert _reply({"content": "<think>x</think>hello"}) == "hello"


def test_extract_tool_call_parses_json_string_arguments():
    out = _reply(
        {
            "content": None,
            "tool_calls": [
                {
                    "function": {
                        "name": "codex_generate",
                        "arguments": '{"prompt": "hi"}',
                    }
                }
            ],
        }
    )
    assert json.loads(out) == {"tool": "codex_generate", "arguments": {"prompt": "hi"}}


def test_extract_tool_call_accepts_object_arguments():
    """Ollama sent objects where OpenAI sends strings; both are accepted."""
    out = _reply(
        {"tool_calls": [{"function": {"name": "codex_edit", "arguments": {"a": 1}}}]}
    )
    assert json.loads(out) == {"tool": "codex_edit", "arguments": {"a": 1}}


def test_extract_tool_call_survives_malformed_arguments():
    out = _reply(
        {"tool_calls": [{"function": {"name": "codex_edit", "arguments": "{not json"}}]}
    )
    assert json.loads(out) == {"tool": "codex_edit", "arguments": {}}


def test_a_tool_call_wins_over_content():
    out = _reply(
        {
            "content": "I will edit that file",
            "tool_calls": [{"function": {"name": "codex_edit", "arguments": "{}"}}],
        }
    )
    assert json.loads(out)["tool"] == "codex_edit"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "<think>only thinking</think>"}}]},
        "not a dict",
    ],
)
def test_extract_reply_returns_empty_rather_than_raising(data):
    assert extract_reply(data) == ""


# --- model resolution -------------------------------------------------------


def _async_client(handler, **kwargs) -> LLMAsyncClient:
    return LLMAsyncClient(
        LLMConfig(base_url="http://lm.test:1234", **kwargs),
        transport=httpx.MockTransport(handler),
    )


def test_configured_model_skips_the_lookup(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("should not have asked the server")

    monkeypatch.setattr(httpx.Client, "get", explode)
    client = LLMChatClient(LLMConfig(base_url="http://lm.test:1234", model="pinned"))
    assert client.resolve_model() == "pinned"


@pytest.mark.asyncio
async def test_async_resolve_model_uses_the_loaded_one():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen/qwen3.6-35b-a3b"}]})

    assert await _async_client(handler).resolve_model() == "qwen/qwen3.6-35b-a3b"


@pytest.mark.asyncio
async def test_async_resolve_model_reports_an_empty_server():
    client = _async_client(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(LLMUnavailable, match="no model loaded"):
        await client.resolve_model()


def test_config_builds_openai_urls():
    config = LLMConfig(base_url="http://lm.test:1234/")
    assert config.chat_url == "http://lm.test:1234/v1/chat/completions"
    assert config.models_url == "http://lm.test:1234/v1/models"


@pytest.mark.asyncio
async def test_unreachable_server_raises_unavailable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailable, match="cannot reach"):
        await _async_client(down).resolve_model()


@pytest.mark.asyncio
async def test_stream_chat_yields_content_without_the_scratchpad():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == "loaded-model"

        def frames():
            for piece in ["<think>", "plotting", "</think>", "Hi", " there"]:
                chunk = {"choices": [{"delta": {"content": piece}}]}
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, content=b"".join(frames()))

    client = _async_client(handler, model="loaded-model")
    out = [d async for d in client.stream_chat([{"role": "user", "content": "hi"}])]
    assert "".join(out) == "Hi there"
