from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.dependencies.database import get_db_session, get_pii_db_session
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.authorization import AuthorizationRepository
from app.repositories.interfaces.pii_mapping import PiiMappingRepository
from app.repositories.interfaces.user import UserRepository
from app.repositories.sqlalchemy.audit_log import SQLAlchemyAuditLogRepository
from app.repositories.sqlalchemy.authorization import SQLAlchemyAuthorizationRepository
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository
from app.repositories.sqlalchemy.user import SQLAlchemyUserRepository


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    return SQLAlchemyUserRepository(session)


def get_authorization_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AuthorizationRepository:
    return SQLAlchemyAuthorizationRepository(session)


def get_pii_mapping_repository(
    session: AsyncSession = Depends(get_pii_db_session),
    settings: Settings = Depends(get_settings),
) -> PiiMappingRepository:
    return SQLAlchemyPiiMappingRepository(
        session=session,
        query_batch_size=settings.pii_mapping_snapshot_batch_size,
    )


def get_audit_log_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AuditLogRepository:
    return SQLAlchemyAuditLogRepository(session)
