from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import PurchaseRequest
from app.domain.enums import PurchaseStatus


class PurchaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, request_id: int) -> PurchaseRequest | None:
        return await self.session.get(PurchaseRequest, request_id)

    async def list(self, *, open_only: bool) -> Sequence[PurchaseRequest]:
        stmt = (
            select(PurchaseRequest)
            .options(
                selectinload(PurchaseRequest.machine), selectinload(PurchaseRequest.created_by)
            )
            .order_by(PurchaseRequest.created_at.desc())
        )
        if open_only:
            stmt = stmt.where(PurchaseRequest.status != PurchaseStatus.DONE)
        else:
            stmt = stmt.where(PurchaseRequest.status == PurchaseStatus.DONE).limit(30)
        result = await self.session.scalars(stmt)
        return result.all()

    async def count_new(self) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(PurchaseRequest)
            .where(PurchaseRequest.status == PurchaseStatus.NEW)
        )
        return count or 0

    async def set_status(self, request: PurchaseRequest, status: PurchaseStatus) -> None:
        request.status = status
        await self.session.flush()
