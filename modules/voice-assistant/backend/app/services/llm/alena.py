from __future__ import annotations

from typing import Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)


class AlenaClient:
    def __init__(self, base_url: str, timeout_s: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def generate(self, prompt: str, session_id: Optional[str] = None) -> str:
        url = f"{self.base_url}/generate"
        payload = {"prompt": prompt}
        if session_id:
            payload["session_id"] = session_id

        timeout = httpx.Timeout(self.timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return ""
            return str(data.get("response", ""))
