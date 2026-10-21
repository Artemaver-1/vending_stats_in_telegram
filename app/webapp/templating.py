import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.clock import Clock
from app.domain.enums import TaskStatus
from app.domain.inspection import CHECKLIST
from app.formatting import (
    CHANNEL_DEVICES,
    CHANNEL_LABELS,
    DISCREPANCY_LABELS,
    EXPENSE_LABELS,
    MONTHS_SHORT,
    PAID_FROM_LABELS,
    WEEKDAYS,
    human_date,
    month_title,
    plural,
    rub,
    span,
    uptime_level,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters.update(
    rub=rub,
    month_title=month_title,
    month_short=lambda d: MONTHS_SHORT[d.month - 1],
    weekday=lambda d: WEEKDAYS[d.weekday()],
    uptime_level=uptime_level,
    percent=lambda v: f"{v:.0%}",
    plural=plural,
    span=span,
)
templates.env.globals.update(
    CHECKLIST=CHECKLIST,
    CHANNEL_DEVICES=CHANNEL_DEVICES,
    CHANNEL_LABELS=CHANNEL_LABELS,
    DISCREPANCY_LABELS=DISCREPANCY_LABELS,
    EXPENSE_LABELS=EXPENSE_LABELS,
    PAID_FROM_LABELS=PAID_FROM_LABELS,
    TaskStatus=TaskStatus,
)


def render(
    request: Request,
    template: str,
    *,
    toast: str | None = None,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    clock: Clock = request.app.state.clock
    today = clock.today()

    def when(day: date) -> str:
        return human_date(day, today)

    response = templates.TemplateResponse(
        request,
        template,
        {
            "today": today,
            "tz": clock.tz,
            "when": when,
            "signer": request.app.state.signer,
            **context,
        },
        status_code=status_code,
    )
    return with_toast(response, toast) if toast else response


def with_toast(response: HTMLResponse, text: str, *, error: bool = False) -> HTMLResponse:
    # JSON escapes keep the header ASCII; app.js shows it as a toast with haptics.
    response.headers["HX-Trigger"] = json.dumps({"toastError" if error else "toast": text})
    return response
