from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.enums import UserRole


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def by_telegram_id(self, telegram_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def register_visitor(self, telegram_id: int, name: str, username: str | None) -> User:
        """Remembers whoever opened the bot; new people wait for an admin to let them in."""
        user = await self.by_telegram_id(telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, name=name, username=username, is_active=False)
            self.session.add(user)
        else:
            user.name, user.username = name, username
        await self.session.flush()
        return user

    async def ensure_admins(self, telegram_ids: Collection[int]) -> None:
        for telegram_id in telegram_ids:
            user = await self.by_telegram_id(telegram_id)
            if user is None:
                user = User(telegram_id=telegram_id, name="Админ")
                self.session.add(user)
            user.role, user.is_active = UserRole.ADMIN, True
        await self.session.flush()

    async def list_all(self) -> Sequence[User]:
        result = await self.session.scalars(
            select(User).order_by(User.is_active.desc(), User.role, User.name)
        )
        return result.all()

    async def active(self, role: UserRole) -> Sequence[User]:
        result = await self.session.scalars(
            select(User).where(User.role == role, User.is_active).order_by(User.name)
        )
        return result.all()

    async def set_access(self, user: User, *, active: bool) -> None:
        if user.role is UserRole.ADMIN and not active:
            raise ValueError("admins are managed through ADMIN_IDS")
        user.is_active = active
        await self.session.flush()

    async def telegram_ids(self, role: UserRole) -> list[int]:
        return [user.telegram_id for user in await self.active(role)]
