from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401  registers tables on Base.metadata
from app.db import Base, Database


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session_factory() as session:
        yield session
