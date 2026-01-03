from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.pipeline import Pipeline
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


def _safe_json_loads(text: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    settings = get_settings()
    pipeline = Pipeline(settings=settings)

    await ws.accept()
    audio_buffer = bytearray()

    async def send(payload: Dict[str, Any]) -> None:
        await ws.send_text(json.dumps(payload))

    try:
        await send({"type": "ready"})

        while True:
            try:
                message = await ws.receive()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")
                return

            if "bytes" in message and message["bytes"] is not None:
                chunk: bytes = message["bytes"]
                audio_buffer.extend(chunk)
                logger.debug("Received audio chunk: %d bytes (total: %d bytes)", len(chunk), len(audio_buffer))
                if len(audio_buffer) > settings.max_audio_bytes:
                    await send({"type": "error", "message": "max_audio_bytes exceeded"})
                    await ws.close(code=1009)
                    return
                await send(
                    {
                        "type": "audio",
                        "event": "chunk",
                        "bytes": len(chunk),
                        "total": len(audio_buffer),
                    }
                )
                continue

            if "text" in message and message["text"] is not None:
                logger.debug("Received text message: %s", message["text"])
                data = _safe_json_loads(message["text"])
                if not data:
                    await send({"type": "error", "message": "invalid JSON message"})
                    continue

                action = data.get("action")
                logger.debug("Received action: %s", action)
                if action == "ping":
                    await send({"type": "pong"})
                    continue

                if action == "start":
                    audio_buffer.clear()
                    logger.info("Started receiving audio bytes")
                    await send({"type": "ack", "event": "start"})
                    continue

                if action == "end":
                    logger.info("Stopped receiving audio bytes (total: %d bytes)", len(audio_buffer))
                    await send(
                        {"type": "ack", "event": "end", "bytes": len(audio_buffer)}
                    )

                    result = await pipeline.run(audio_wav_bytes=bytes(audio_buffer))
                    await send({"type": "stt", "text": result.get("transcript", "")})

                    if result.get("llm_enabled") and pipeline.ollama is not None:
                        prompt = result.get("prompt", "")
                        await send(
                            {
                                "type": "llm",
                                "event": "start",
                                "model": pipeline.ollama.model,
                                "prompt": prompt,
                            }
                        )

                        full = ""
                        async for delta in pipeline.ollama.stream_generate(
                            prompt=prompt
                        ):
                            full += delta
                            await send({"type": "llm", "delta": delta})

                        await send({"type": "llm", "event": "end", "text": full})
                    else:
                        await send({"type": "llm", "event": "skipped"})

                    continue

                await send({"type": "error", "message": f"unknown action: {action}"})
                continue

    except Exception as exc:  # best-effort error surface to client
        logger.exception("WebSocket error")
        try:
            await send({"type": "error", "message": str(exc)})
        except Exception:
            # Connection already closed, ignore
            pass
        finally:
            try:
                await ws.close(code=1011)
            except Exception:
                pass
