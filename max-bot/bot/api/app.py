"""FastAPI-приложение."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Летописец API",
        description="REST API для транскрибации аудио/видео",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app
