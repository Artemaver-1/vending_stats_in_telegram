from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class Repository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: int) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def list(self) -> Sequence[ModelT]:
        result = await self.session.scalars(select(self.model))
        return result.all()

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
