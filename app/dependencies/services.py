from fastapi import Depends

from app.core.config import Settings, get_settings
from app.dependencies.database import get_unit_of_work
from app.dependencies.repositories import (
    get_audit_log_repository,
    get_authorization_repository,
    get_pii_mapping_repository,
    get_user_repository,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.pii_database.session import PiiAsyncSessionFactory
from app.infrastructure.trino.client import TrinoClient, TrinoPythonClient
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.authorization import AuthorizationRepository
from app.repositories.interfaces.pii_mapping import PiiMappingRepository
from app.repositories.interfaces.user import UserRepository
from app.repositories.sqlalchemy.pii_mapping import SQLAlchemyPiiMappingRepository
from app.services.auth import AuthService
from app.services.authorization import AuthorizationService
from app.services.data_query import DataQueryService
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.services.pii_mapping_snapshot import load_pii_mapping_snapshot
from app.services.user import UserService

_pii_mapping_cache: InMemoryPiiMappingCache | None = None
_trino_client: TrinoPythonClient | None = None


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    authorization: AuthorizationRepository = Depends(get_authorization_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(
        users=users,
        authorization=authorization,
        uow=uow,
        settings=settings,
    )


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
    authorization: AuthorizationRepository = Depends(get_authorization_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> UserService:
    return UserService(
        users=users,
        authorization=authorization,
        uow=uow,
        settings=settings,
    )


def get_authorization_service(
    authorization: AuthorizationRepository = Depends(get_authorization_repository),
    users: UserRepository = Depends(get_user_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> AuthorizationService:
    return AuthorizationService(
        authorization=authorization,
        users=users,
        uow=uow,
    )


def get_trino_client(
    settings: Settings = Depends(get_settings),
) -> TrinoClient:
    global _trino_client
    if _trino_client is None:
        _trino_client = TrinoPythonClient(settings=settings)
    return _trino_client


async def close_trino_client() -> None:
    global _trino_client
    if _trino_client is None:
        return
    await _trino_client.close()
    _trino_client = None


def get_pii_mapping_cache(
    settings: Settings = Depends(get_settings),
) -> InMemoryPiiMappingCache:
    global _pii_mapping_cache
    if _pii_mapping_cache is None:
        _pii_mapping_cache = InMemoryPiiMappingCache(
            missing_ttl_seconds=settings.pii_mapping_missing_ttl_seconds,
        )
    return _pii_mapping_cache


async def initialize_pii_mapping_cache(settings: Settings) -> tuple[int, int]:
    cache = get_pii_mapping_cache(settings)
    async with PiiAsyncSessionFactory() as session:
        repository = SQLAlchemyPiiMappingRepository(
            session=session,
            query_batch_size=settings.pii_mapping_snapshot_batch_size,
        )
        loaded = await load_pii_mapping_snapshot(
            repository=repository,
            cache=cache,
            batch_size=settings.pii_mapping_snapshot_batch_size,
        )
    return loaded, cache.size


def get_data_query_service(
    settings: Settings = Depends(get_settings),
    trino: TrinoClient = Depends(get_trino_client),
    pii_mappings: PiiMappingRepository = Depends(get_pii_mapping_repository),
    audit_logs: AuditLogRepository = Depends(get_audit_log_repository),
    mapping_cache: InMemoryPiiMappingCache = Depends(get_pii_mapping_cache),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> DataQueryService:
    return DataQueryService(
        settings=settings,
        trino=trino,
        pii_mappings=pii_mappings,
        audit_logs=audit_logs,
        mapping_cache=mapping_cache,
        uow=uow,
    )
