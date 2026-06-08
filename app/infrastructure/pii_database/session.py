from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

pii_engine: AsyncEngine = create_async_engine(
    settings.pii_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
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
