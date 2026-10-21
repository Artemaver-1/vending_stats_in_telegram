from fastapi import APIRouter

from app.webapp.routes.admin import (
    dashboard,
    fleet,
    reconciliation,
    rent,
    reports,
    statement,
    tasks,
    treasury,
)

router = APIRouter()
for module in (dashboard, tasks, reports, statement, treasury, rent, fleet, reconciliation):
    router.include_router(module.router)
