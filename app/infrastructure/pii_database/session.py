from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import get_settings
from app.infrastructure.database.engine import create_postgres_async_engine

settings = get_settings()

pii_engine: AsyncEngine = create_postgres_async_engine(
    settings.pii_database_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout_seconds=30.0,
    pool_recycle_seconds=1800,
    connect_timeout_seconds=10.0,
    statement_timeout_seconds=60.0,
)

PiiAsyncSessionFactory = async_sessionmaker(
    bind=pii_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_pii_session() -> AsyncIterator[AsyncSession]:
    async with PiiAsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()
