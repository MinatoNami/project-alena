from __future__ import annotations

from typing import AsyncGenerator, Optional

from modules.llm import LLMAsyncClient, LLMConfig


class LMStudioClient:
    def __init__(self, base_url: str, model: str = "", timeout_s: float = 120.0):
        config = LLMConfig(base_url=base_url, model=model, timeout_s=timeout_s)
        self._client = LLMAsyncClient(config)

    @property
    def model(self) -> str:
        # Empty until the first request resolves whatever LM Studio has loaded.
        return self._client.model or "(loaded model)"

    async def stream_generate(
        self, prompt: str, system: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        async for chunk in self._client.stream_generate(prompt=prompt, system=system):
            yield chunk
