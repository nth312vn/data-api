from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_session
from app.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from app.infrastructure.pii_database.session import get_pii_session


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_pii_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_pii_session():
        yield session


def get_unit_of_work(
    session: AsyncSession = Depends(get_db_session),
) -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork(session)
