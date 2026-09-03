from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_settings
from modules.llm import LLMAsyncClient, LLMConfig, LLMUnavailable

router = APIRouter()


def _build_client() -> LLMAsyncClient:
    settings = get_settings()
    if not settings.llm_enabled:
        raise HTTPException(status_code=503, detail="LLM is disabled")
    config = LLMConfig(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout,
    )
    return LLMAsyncClient(config)


@router.get("/v1/models")
async def list_models():
    client = _build_client()
    try:
        return JSONResponse(content=await client.list_models())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LM Studio unreachable: {exc}")


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Proxy the browser's chat to LM Studio.

    The browser cannot reach LM Studio directly — it is on another host behind
    the tailnet, and a page served over HTTPS may not call it over plain HTTP.
    Streaming replies are server-sent events, so the body is forwarded through
    unchanged rather than re-encoded.
    """
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    client = _build_client()

    # The caller does not get to pick the model: LM Studio serves whatever is
    # loaded, and a stale name from a cached page would 404 the whole request.
    try:
        payload["model"] = await client.resolve_model()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if payload.get("stream") is True:

        async def _stream() -> AsyncGenerator[str, None]:
            async for line in client.stream_chat_raw(payload):
                yield f"{line}\n\n"

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return JSONResponse(content=await client.post_chat(payload))
