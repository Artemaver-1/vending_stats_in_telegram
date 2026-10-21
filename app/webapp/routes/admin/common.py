from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.services.tasks import TaskService
from app.webapp.templating import render


async def admin_page(
    request: Request,
    session: AsyncSession,
    template: str,
    *,
    tab: str,
    toast: str | None = None,
    **context: Any,
) -> HTMLResponse:
    """Renders an admin screen together with the tab bar and its badge.

    Commits first, so a screen returned after a change never shows unsaved state.
    """
    await session.commit()
    clock: Clock = request.app.state.clock
    unseen = await TaskService(session, clock).count_unseen_reports()
    return render(request, template, tab=tab, unseen_reports=unseen, toast=toast, **context)


def optional_int(value: str | None) -> int | None:
    return int(value) if value else None
