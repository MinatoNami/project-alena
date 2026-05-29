from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, Optional

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    async def post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}{endpoint}", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def stream_lines(
        self, endpoint: str, payload: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}{endpoint}", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        yield line

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        payload: Dict[str, Any] = {
            "model": self.model,
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
