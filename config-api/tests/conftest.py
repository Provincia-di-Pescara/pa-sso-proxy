import pytest
import pytest_asyncio
from sqlalchemy import JSON, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Monkey-patch PostgreSQL types before importing models
import sqlalchemy.dialects.postgresql as pg_dialect
pg_dialect.ARRAY = lambda x, **kw: JSON()
pg_dialect.JSONB = JSON

from app.models import Base


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
