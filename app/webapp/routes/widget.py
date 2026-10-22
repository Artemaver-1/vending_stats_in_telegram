from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.api.deps import ClockDep, SessionDep
from app.services.widget import WidgetService
from app.webapp.auth import CurrentUser
from app.webapp.deps import NotifierDep
from app.webapp.templating import render, with_toast

router = APIRouter()

SCRIPT_TEMPLATE = Path(__file__).parent.parent / "widget" / "silomery.js"


@router.get("/widget/{token}")
async def widget_data(token: str, session: SessionDep, clock: ClockDep) -> dict[str, Any]:
    widgets = WidgetService(session, clock)
    if await widgets.user_by_token(token) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return await widgets.snapshot()


@router.post("/app/service/widget", response_class=HTMLResponse)
async def send_widget_script(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    notifier: NotifierDep,
) -> HTMLResponse:
    token = await WidgetService(session, clock).token_for(user)
    await session.commit()
    # A fixed address outlives tunnel restarts, so the widget never has to look it up.
    settings = request.app.state.settings
    base = (settings.webapp_url or str(request.base_url)).rstrip("/")
    base = base.replace("http://", "https://")
    script = (
        SCRIPT_TEMPLATE.read_text()
        .replace("{{TOKEN}}", token)
        .replace("{{BOT}}", request.app.state.bot_username or "")
        .replace("{{URL}}", base)
    )
    await notifier.send_document(
        user.telegram_id,
        "Силомеры.js",
        script.encode(),
        "📱 Виджет для iPhone. Откройте файл → «Поделиться» → Scriptable, затем добавьте "
        "на экран «Домой» виджет Scriptable и выберите в нём скрипт «Силомеры».",
    )
    return with_toast(render(request, "service/widget_sent.html"), "Скрипт отправлен в чат с ботом")
