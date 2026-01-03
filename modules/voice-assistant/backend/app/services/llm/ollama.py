from __future__ import annotations

import json
from typing import AsyncGenerator, Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
        }
        if system:
            payload["system"] = system

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    chunk = data.get("response")
                    if chunk:
                        yield str(chunk)

                    if data.get("done") is True:
                        break
