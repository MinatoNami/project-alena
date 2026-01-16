from __future__ import annotations

from typing import AsyncGenerator, Optional

from modules.ollama import OllamaAsyncClient, OllamaConfig


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0):
        self.model = model
        config = OllamaConfig(base_url=base_url, model=model, timeout_s=timeout_s)
        self._client = OllamaAsyncClient(config)

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        async for chunk in self._client.stream_generate(prompt=prompt, system=system):
            yield chunk
