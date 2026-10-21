from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.purchases import PurchaseService
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
    new_purchases = await PurchaseService(session).count_new()
    return render(request, template, tab=tab, new_purchases=new_purchases, toast=toast, **context)


def optional_int(value: str | None) -> int | None:
    return int(value) if value else None
