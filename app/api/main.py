from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import finance, health, hooks
from app.bot.client import make_bot
from app.bot.setup import build_dispatcher
from app.bot.webapp_link import WebAppLink
from app.clock import Clock
from app.config import Settings, get_settings
from app.db import Database
from app.integrations.smartvend import SmartVendClient
from app.services.file_drop import FileDrop
from app.services.notifications import TelegramNotifier
from app.webapp.auth import LinkSigner, admin_user
from app.webapp.routes import machines, service, shell, widget
from app.webapp.routes.admin import router as admin_router
from app.worker.jobs import ServiceJobs, TelemetryJobs

STATIC_DIR = Path(__file__).parent.parent / "webapp" / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bot = make_bot(settings)
        app.state.bot = bot
        app.state.db = Database(settings.database_url)
        # Through the Telegram relay big uploads get cut off, so files go out as links.
        drop = None
        if settings.telegram_api_url:
            drop = FileDrop(app.state.db, settings.telegram_api_url)
        app.state.file_drop = drop
        app.state.notifier = TelegramNotifier(bot, drop)
        app.state.service_jobs = ServiceJobs(app.state.db, app.state.notifier, app.state.clock)
        if settings.hook_secret is not None:
            webapp = WebAppLink(settings.webapp_url, settings.tunnel_metrics_url)
            app.state.dispatcher = build_dispatcher(
                bot, app.state.db, webapp, media_url=settings.telegram_reach_url
            )
        smartvend = None
        if settings.smartvend_api_key is not None:
            # The refresh button waits for this client, and the tunnel drops requests after
            # about 100 seconds, so here it gives up fast instead of retrying like the worker.
            smartvend = SmartVendClient(
                settings.smartvend_api_key.get_secret_value(),
                settings.smartvend_base_url,
                timeout=20,
                connect_timeout=8,
                retries=1,
            )
            app.state.telemetry = TelemetryJobs(
                settings, app.state.db, smartvend, app.state.notifier, app.state.clock
            )
        yield
        if smartvend is not None:
            await smartvend.close()
        await bot.session.close()
        await app.state.db.dispose()

    docs = "/docs" if settings.api_docs else None
    app = FastAPI(
        title="Vending Ops API",
        version=__version__,
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.clock = Clock(settings.tz)
    app.state.signer = LinkSigner(settings.bot_token.get_secret_value())
    app.state.bot_username = None

    app.include_router(health.router)
    app.include_router(hooks.router)
    # The JSON API is reachable through the same tunnel as the Mini App, so it's admin-only.
    app.include_router(finance.router, dependencies=[Depends(admin_user)])
    app.include_router(shell.router)
    app.include_router(service.router)
    app.include_router(machines.router)
    app.include_router(widget.router)
    app.include_router(admin_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/app")

    @app.middleware("http")
    async def screens_need_the_shell(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Screens are htmx fragments; opening one directly (a reload) goes back to the shell.
        path = request.url.path
        is_screen = path.startswith(("/app/admin", "/app/service", "/app/machines"))
        if is_screen and request.method == "GET" and "HX-Request" not in request.headers:
            return RedirectResponse("/app")
        return await call_next(request)

    return app
