from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import get_settings
from app.infrastructure.database.engine import create_postgres_async_engine

settings = get_settings()

engine: AsyncEngine = create_postgres_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout_seconds=30.0,
    pool_recycle_seconds=1800,
    connect_timeout_seconds=10.0,
    statement_timeout_seconds=60.0,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
