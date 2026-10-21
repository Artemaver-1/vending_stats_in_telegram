from fastapi import APIRouter

from app.webapp.routes.admin import (
    dashboard,
    fleet,
    money,
    reconciliation,
    rent,
    reports,
    statement,
    tasks,
)

router = APIRouter()
for module in (dashboard, tasks, reports, statement, money, rent, fleet, reconciliation):
    router.include_router(module.router)
