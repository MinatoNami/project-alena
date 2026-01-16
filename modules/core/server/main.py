from __future__ import annotations

import os
from typing import Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from modules.core.controller.agent import run_agent
from modules.core.controller.memory import ConversationMemory


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class GenerateResponse(BaseModel):
    response: str


class HealthResponse(BaseModel):
    ok: bool = True


_SESSION_MEMORY: Dict[str, ConversationMemory] = {}


def _get_memory(session_id: Optional[str]) -> ConversationMemory:
    if not session_id:
        return ConversationMemory()
    memory = _SESSION_MEMORY.get(session_id)
    if memory is None:
        memory = ConversationMemory()
        _SESSION_MEMORY[session_id] = memory
    return memory


def create_app() -> FastAPI:
    app = FastAPI(title="alena-controller")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @app.post("/generate", response_model=GenerateResponse)
    async def generate(payload: GenerateRequest) -> GenerateResponse:
        memory = _get_memory(payload.session_id)
        outputs = []

        def _sink(text: str) -> None:
            outputs.append(text)

        response = await run_agent(
            payload.prompt,
            memory=memory,
            output_sink=_sink,
            return_output=True,
        )

        if response is None:
            response = ""

        return GenerateResponse(response=response)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("ALENA_CONTROLLER_HOST", "0.0.0.0")
    port = int(os.getenv("ALENA_CONTROLLER_PORT", "9000"))
    uvicorn.run("modules.core.server.main:app", host=host, port=port, reload=False)
