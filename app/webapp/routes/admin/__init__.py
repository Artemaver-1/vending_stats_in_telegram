from fastapi import APIRouter

from app.webapp.routes.admin import dashboard, fleet, money, rent, tasks

router = APIRouter()
for module in (dashboard, tasks, money, rent, fleet):
    router.include_router(module.router)
