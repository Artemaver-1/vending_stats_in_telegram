from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import finance, health
from app.config import Settings, get_settings
from app.db import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings.database_url)
        app.state.settings = settings
        yield
        await app.state.db.dispose()

    app = FastAPI(title="Vending Ops API", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(finance.router)
    return app
