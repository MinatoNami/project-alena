from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ws import router as ws_router
from app.api.llm import router as llm_router
from app.config import get_settings
from app.services.stt.remote import RemoteSTT


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    stt = RemoteSTT(settings=settings)

    @app.get("/health")
    async def health() -> dict:
        # Report the remote transcriber too: "voice does nothing" is nearly
        # always text-whisperer being unreachable rather than this process.
        return {
            "ok": True,
            "llm_route": settings.llm_route,
            "stt": {
                "url": settings.text_whisperer_url,
                "reachable": await stt.healthy(),
            },
        }

    app.include_router(ws_router)
    app.include_router(llm_router)
    return app


app = create_app()
