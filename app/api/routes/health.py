from datetime import date

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbDep, SessionDep
from app.db.models import SyncState

router = APIRouter(tags=["health"])


class SourceState(BaseModel):
    source: str
    synced_through: date | None
    last_error: str | None


class HealthResponse(BaseModel):
    database: bool
    sources: list[SourceState]


@router.get("/health")
async def health(db: DbDep, session: SessionDep, response: Response) -> HealthResponse:
    if not await db.ping():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(database=False, sources=[])

    states = await session.scalars(select(SyncState).order_by(SyncState.source))
    return HealthResponse(
        database=True,
        sources=[
            SourceState(source=s.source, synced_through=s.synced_through, last_error=s.last_error)
            for s in states
        ],
    )
