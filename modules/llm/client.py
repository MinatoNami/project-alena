"""Client for an OpenAI-compatible inference server (LM Studio).

LM Studio serves `/v1/chat/completions`, so this speaks the OpenAI wire format
rather than Ollama's. Two differences from that older client matter to callers:

* Tool calls come back in `message.tool_calls` with `arguments` as a JSON
  *string*, not an object. They are parsed here so callers always get a dict.
* Reasoning models (qwen3, deepseek-r1, ...) emit their scratchpad before the
  answer. It is stripped here, because the agent loop parses the reply as JSON
  and a `<think>` block in front of it makes every tool call unparseable.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx


# Reasoning models wrap their scratchpad in these; it is not the answer.
_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
# A reply cut off mid-thought never closes the tag. Drop from the tag onward
# rather than handing the caller a scratchpad it will try to parse as JSON.
_THINK_UNCLOSED = re.compile(r"<(think|thinking|reasoning)>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove a reasoning model's scratchpad from its reply."""
    if not text:
        return ""
    text = _THINK.sub("", text)
    text = _THINK_UNCLOSED.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://127.0.0.1:1234"
    # Blank means "whatever the server currently has loaded", which is usually
    # what you want with LM Studio: the model is chosen in the app, not here.
    model: str = ""
    timeout_s: float = 120.0
    debug: bool = False

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def chat_url(self) -> str:
        return f"{self.normalized_base_url()}/v1/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.normalized_base_url()}/v1/models"


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """The server is not reachable, or has no model loaded.

    Worth its own type because it is the one failure that is nobody's fault and
    fixes itself: the same request works once LM Studio is up with a model.
    """


def _first_loaded_model(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    entries = data.get("data")
    if not isinstance(entries, list):
        return ""
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            return str(entry["id"])
    return ""


class LLMChatClient:
    """Blocking chat client. Used by the agent loop, which is synchronous."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._config = config
        self._resolved_model: Optional[str] = None
        # Tests pass an httpx.MockTransport here; nothing else should.
        self._transport = transport

    def _client(self, timeout: httpx.Timeout) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    @property
    def model(self) -> str:
        return self._config.model or self._resolved_model or ""

    def resolve_model(self) -> str:
        """Whatever the server has loaded, unless one was configured."""
        if self._config.model:
            return self._config.model
        if self._resolved_model:
            return self._resolved_model

        try:
            with self._client(httpx.Timeout(10.0)) as client:
                response = client.get(self._config.models_url)
                response.raise_for_status()
                model = _first_loaded_model(response.json())
        except Exception as exc:
            raise LLMUnavailable(
                f"cannot reach LM Studio at {self._config.normalized_base_url()}: {exc}"
            ) from exc

        if not model:
            raise LLMUnavailable(
                f"LM Studio at {self._config.normalized_base_url()} has no model loaded"
            )

        self._resolved_model = model
        return model

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Return the assistant's reply.

        A tool call is returned as the JSON the agent loop already expects —
        `{"tool": ..., "arguments": {...}}` — so native tool calling and a model
        that merely writes that JSON into its reply land on the same code path.
        """
        payload: Dict[str, Any] = {
            "model": self.resolve_model(),
            "messages": (
                [{"role": "system", "content": system_prompt}, *messages]
                if system_prompt
                else list(messages)
            ),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        for attempt in range(2):
            try:
                with self._client(httpx.Timeout(self._config.timeout_s)) as client:
                    response = client.post(self._config.chat_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPError as exc:
                raise LLMUnavailable(f"LM Studio request failed: {exc}") from exc

            content = extract_reply(data)
            if content:
                return content

            if attempt == 0:
                time.sleep(0.5)

        return ""


class LLMAsyncClient:
    """Async client for the voice backend: streaming replies and proxying."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self._config = config
        self._resolved_model: Optional[str] = None
        # Tests pass an httpx.MockTransport here; nothing else should.
        self._transport = transport

    def _client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    @property
    def model(self) -> str:
        return self._config.model or self._resolved_model or ""

    async def resolve_model(self) -> str:
        if self._config.model:
            return self._config.model
        if self._resolved_model:
            return self._resolved_model

        try:
            async with self._client(httpx.Timeout(10.0)) as client:
                response = await client.get(self._config.models_url)
                response.raise_for_status()
                model = _first_loaded_model(response.json())
        except Exception as exc:
            raise LLMUnavailable(
                f"cannot reach LM Studio at {self._config.normalized_base_url()}: {exc}"
            ) from exc

        if not model:
            raise LLMUnavailable(
                f"LM Studio at {self._config.normalized_base_url()} has no model loaded"
            )

        self._resolved_model = model
        return model

    async def list_models(self) -> Dict[str, Any]:
        async with self._client(httpx.Timeout(10.0)) as client:
            response = await client.get(self._config.models_url)
            response.raise_for_status()
            return response.json()

    async def post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with self._client(httpx.Timeout(self._config.timeout_s)) as client:
            response = await client.post(self._config.chat_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def stream_chat_raw(self, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Yield the server-sent-event lines verbatim, for proxying to a browser."""
        async with self._client(httpx.Timeout(self._config.timeout_s)) as client:
            async with client.stream("POST", self._config.chat_url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Yield content deltas, with any reasoning scratchpad filtered out."""
        payload: Dict[str, Any] = {
            "model": await self.resolve_model(),
            "messages": (
                [{"role": "system", "content": system_prompt}, *messages]
                if system_prompt
                else list(messages)
            ),
            "stream": True,
        }

        reasoning = ReasoningFilter()
        async for line in self.stream_chat_raw(payload):
            chunk = _parse_sse_data(line)
            if chunk is None:
                continue

            delta = _delta_content(chunk)
            if not delta:
                continue

            visible = reasoning.feed(delta)
            if visible:
                yield visible

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Single-turn convenience wrapper over stream_chat."""
        async for delta in self.stream_chat(
            [{"role": "user", "content": prompt}], system_prompt=system
        ):
            yield delta


def _parse_sse_data(line: str) -> Optional[Dict[str, Any]]:
    """Turn one `data: {...}` SSE line into a dict; None for anything else."""
    if not line.startswith("data:"):
        return None
    body = line[len("data:") :].strip()
    if not body or body == "[DONE]":
        return None
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _delta_content(chunk: Dict[str, Any]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


_OPEN_TAGS = ("<think>", "<thinking>", "<reasoning>")
_CLOSE_TAGS = ("</think>", "</thinking>", "</reasoning>")


def _earliest_tag(text: str, tags: tuple[str, ...]) -> tuple[int, str]:
    """Index and identity of whichever tag appears first; (-1, "") for none."""
    best_at = -1
    best_tag = ""
    for tag in tags:
        at = text.find(tag)
        if at != -1 and (best_at == -1 or at < best_at):
            best_at, best_tag = at, tag
    return best_at, best_tag


class ReasoningFilter:
    """Drops a reasoning model's scratchpad from a token stream.

    strip_reasoning() cannot do this job: the tags arrive token by token, so
    whether we are inside a <think> span has to be remembered between chunks.

    A tag split across two chunks would slip through. LM Studio emits them
    whole, and the cost of being wrong is a few leaked characters rather than a
    corrupted stream, so this does not buffer to guard against it.
    """

    def __init__(self) -> None:
        self._in_reasoning = False

    @property
    def in_reasoning(self) -> bool:
        return self._in_reasoning

    def feed(self, delta: str) -> str:
        """Return the part of `delta` that belongs in the answer."""
        kept: list[str] = []
        remaining = delta

        while remaining:
            tags = _CLOSE_TAGS if self._in_reasoning else _OPEN_TAGS
            at, tag = _earliest_tag(remaining, tags)

            if at == -1:
                if not self._in_reasoning:
                    kept.append(remaining)
                break

            if not self._in_reasoning:
                kept.append(remaining[:at])
            remaining = remaining[at + len(tag) :]
            self._in_reasoning = not self._in_reasoning

        return "".join(kept)


def extract_reply(data: Any) -> str:
    """Pull the reply out of a chat-completions response.

    Returns the assistant's text, or — when the model called a tool — the
    `{"tool": ..., "arguments": {...}}` JSON the agent loop parses.
    """
    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first = choices[0]
    if not isinstance(first, dict):
        return ""

    message = first.get("message")
    if not isinstance(message, dict):
        return ""

    tool_call = _extract_tool_call(message)
    if tool_call:
        return json.dumps(tool_call)

    content = message.get("content")
    if isinstance(content, str):
        cleaned = strip_reasoning(content)
        if cleaned:
            return cleaned

    return ""


def _extract_tool_call(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None

    first = tool_calls[0]
    if not isinstance(first, dict):
        return None

    function = first.get("function")
    if not isinstance(function, dict):
        return None

    name = function.get("name")
    if not name:
        return None

    # OpenAI-shaped servers send arguments as a JSON string; Ollama sent an
    # object. Accept either so a mixed fleet does not need two code paths.
    raw_args = function.get("arguments", {})
    if isinstance(raw_args, str):
        try:
            arguments = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            arguments = {}
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        arguments = {}

    return {"tool": str(name), "arguments": arguments}
