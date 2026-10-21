import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
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
        # Recreating the schema also clears tables of models that no longer exist.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def session(db: Database) -> AsyncIterator[AsyncSession]:
    async with db.session_factory() as session:
        yield session
