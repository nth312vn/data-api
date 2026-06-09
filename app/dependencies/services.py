from fastapi import Depends

from app.core.config import Settings, get_settings
from app.dependencies.database import get_unit_of_work
from app.dependencies.repositories import (
    get_audit_log_repository,
    get_pii_mapping_repository,
    get_user_repository,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient, TrinoPythonClient
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.pii_mapping import PiiMappingRepository
from app.repositories.interfaces.user import UserRepository
from app.services.auth import AuthService
from app.services.data_query import DataQueryService
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.services.user import UserService

_pii_mapping_cache: InMemoryPiiMappingCache | None = None
_trino_client: TrinoPythonClient | None = None


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(users=users, uow=uow, settings=settings)


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> UserService:
    return UserService(users=users, uow=uow, settings=settings)


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
            max_size=settings.pii_mapping_cache_max_size,
        )
    return _pii_mapping_cache


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
