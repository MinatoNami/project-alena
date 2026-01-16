from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_s: float = 120.0
    debug: bool = False

    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


class OllamaChatClient:
    def __init__(self, config: OllamaConfig):
        self._config = config

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        system_prompt: Optional[str] = None,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "stream": False,
        }
        if system_prompt:
            payload["messages"] = [
                {"role": "system", "content": system_prompt},
                *messages,
            ]

        for attempt in range(2):
            timeout = httpx.Timeout(self._config.timeout_s)
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{self._config.normalized_base_url()}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            if self._config.debug:
                # Avoid logging large payloads; caller can log if needed.
                pass

            content = _extract_chat_content_or_tool_call(data)
            if content:
                return content

            if attempt == 0:
                time.sleep(0.5)

        return ""


class OllamaAsyncClient:
    def __init__(self, config: OllamaConfig):
        self._config = config

    async def post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        timeout = httpx.Timeout(self._config.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._config.normalized_base_url()}{endpoint}",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def stream_lines(
        self, endpoint: str, payload: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        timeout = httpx.Timeout(self._config.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{self._config.normalized_base_url()}{endpoint}", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield line

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        payload: Dict[str, Any] = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": True,
        }
        if system:
            payload["system"] = system

        async for line in self.stream_lines("/api/generate", payload):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            chunk = data.get("response")
            if chunk:
                yield str(chunk)

            if data.get("done") is True:
                break


def _extract_chat_content_or_tool_call(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    message = data.get("message", {}) if isinstance(data, dict) else {}
    if isinstance(message, dict):
        content = message.get("content") or ""
        if isinstance(content, str) and content.strip():
            return content

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first = tool_calls[0] or {}
            function = first.get("function") or {}
            name = function.get("name")
            arguments = function.get("arguments", {})
            if name:
                tool_payload = {
                    "tool": name,
                    "arguments": arguments,
                }
                return json.dumps(tool_payload)

    fallback = data.get("response")
    if isinstance(fallback, str) and fallback.strip():
        return fallback

    return ""
