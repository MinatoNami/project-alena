from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from modules.ollama import OllamaAsyncClient, OllamaConfig

router = APIRouter()


def _build_client() -> OllamaAsyncClient:
    settings = get_settings()
    if not settings.ollama_enabled:
        raise HTTPException(status_code=503, detail="Ollama is disabled")
    config = OllamaConfig(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_s=settings.ollama_timeout,
    )
    return OllamaAsyncClient(config)


@router.post("/api/chat")
async def chat_proxy(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    settings = get_settings()
    payload["model"] = settings.ollama_model

    client = _build_client()

    if payload.get("stream") is True:

        async def _stream() -> AsyncGenerator[str, None]:
            async for line in client.stream_lines("/api/chat", payload):
                yield f"{line}\n"

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    data = await client.post_json("/api/chat", payload)
    return JSONResponse(content=data)


@router.post("/api/generate")
async def generate_proxy(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    settings = get_settings()
    payload["model"] = settings.ollama_model

    client = _build_client()

    if payload.get("stream") is True:

        async def _stream() -> AsyncGenerator[str, None]:
            async for line in client.stream_lines("/api/generate", payload):
                yield f"{line}\n"

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    data = await client.post_json("/api/generate", payload)
    return JSONResponse(content=data)
