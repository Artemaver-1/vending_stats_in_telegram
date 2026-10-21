from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import Location, Machine
from app.repositories.base import Repository


class LocationRepository(Repository[Location]):
    model = Location

    async def list_active(self) -> Sequence[Location]:
        result = await self.session.scalars(
            select(Location).where(Location.is_active).order_by(Location.name)
        )
        return result.all()


class MachineRepository(Repository[Machine]):
    model = Machine

    async def list_active(self) -> Sequence[Machine]:
        result = await self.session.scalars(
            select(Machine).where(Machine.is_active).order_by(Machine.name)
        )
        return result.all()

    async def by_location(self, location_id: int) -> Sequence[Machine]:
        result = await self.session.scalars(
            select(Machine).where(Machine.location_id == location_id, Machine.is_active)
        )
        return result.all()
