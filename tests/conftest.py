import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401  registers tables on Base.metadata
from app.db import Base, Database

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://vending:vending@localhost:5432/vending_test"
)


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    database = Database(TEST_DATABASE_URL)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session_factory() as session:
        yield session
