import asyncio

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.dependencies.database import get_unit_of_work
from app.dependencies.repositories import (
    get_audit_log_repository,
    get_user_repository,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.pii_database.session import PiiAsyncSessionFactory
from app.infrastructure.trino.client import TrinoClient, TrinoPythonClient
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.user import UserRepository
from app.repositories.sqlalchemy.account_map import SQLAlchemyAccountMapRepository
from app.services.account_map_in_memory import AccountMapInMemory
from app.services.audit_log import AuditLogService
from app.services.auth import AuthService
from app.services.pii_mapping_snapshot import load_pii_mapping_snapshot
from app.services.query_engine import PiiMapper, PowerBiDataService, UsersDataService
from app.services.query_engine.dynamic_routes import (
    DynamicRouteRegistry,
    DynamicRouteService,
)
from app.services.user import UserService

logger = get_logger(__name__)

_account_map_in_memory: AccountMapInMemory | None = None
_trino_client: TrinoPythonClient | None = None
_dynamic_route_registry: DynamicRouteRegistry | None = None


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(
        users=users,
        uow=uow,
        settings=settings,
    )


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> UserService:
    return UserService(
        users=users,
        uow=uow,
        settings=settings,
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


def get_account_map_in_memory() -> AccountMapInMemory:
    global _account_map_in_memory
    if _account_map_in_memory is None:
        _account_map_in_memory = AccountMapInMemory()
    return _account_map_in_memory


async def initialize_account_map_in_memory(settings: Settings) -> tuple[int, int]:
    """Load the full PII mapping snapshot into cache at startup.

    Retries up to pii_sync_init_max_retries times on failure with
    pii_sync_init_retry_delay_seconds between attempts.

    If all retries fail, raises RuntimeError to fail the application startup.
    """
    cache = get_account_map_in_memory()
    max_retries = settings.pii_sync_init_max_retries
    retry_delay = settings.pii_sync_init_retry_delay_seconds
    last_exc: BaseException | None = None

    for attempt in range(1, max_retries + 1):
        try:
            async with PiiAsyncSessionFactory() as session:
                repository = SQLAlchemyAccountMapRepository(
                    session=session,
                    query_batch_size=settings.pii_mapping_snapshot_batch_size,
                )
                loaded = await load_pii_mapping_snapshot(
                    repository=repository,
                    cache=cache,
                    batch_size=settings.pii_mapping_snapshot_batch_size,
                )
            return loaded, cache.size
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "pii_cache_init_failed attempt=%d/%d error=%s",
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

    logger.critical(
        "pii_cache_init_all_retries_failed max_retries=%d error=%s",
        max_retries,
        last_exc,
    )
    raise RuntimeError(
        f"PII mapping cache failed to initialize after {max_retries} retries"
    ) from last_exc


def get_pii_mapper(
    mapping_cache: AccountMapInMemory = Depends(get_account_map_in_memory),
) -> PiiMapper:
    return PiiMapper(
        mapping_cache=mapping_cache,
    )


def get_power_bi_service(
    settings: Settings = Depends(get_settings),
    trino: TrinoClient = Depends(get_trino_client),
    pii_mapper: PiiMapper = Depends(get_pii_mapper),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> PowerBiDataService:
    return PowerBiDataService(
        settings=settings,
        trino=trino,
        pii_mapper=pii_mapper,
        uow=uow,
    )


def get_users_data_service(
    settings: Settings = Depends(get_settings),
    trino: TrinoClient = Depends(get_trino_client),
    pii_mapper: PiiMapper = Depends(get_pii_mapper),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> UsersDataService:
    return UsersDataService(
        settings=settings,
        trino=trino,
        pii_mapper=pii_mapper,
        uow=uow,
    )


def get_audit_log_service(
    audit_logs: AuditLogRepository = Depends(get_audit_log_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
) -> AuditLogService:
    return AuditLogService(
        audit_logs=audit_logs,
        uow=uow,
    )


def get_dynamic_route_registry() -> DynamicRouteRegistry:
    global _dynamic_route_registry
    if _dynamic_route_registry is None:
        _dynamic_route_registry = DynamicRouteRegistry()
    return _dynamic_route_registry


def get_dynamic_route_service(
    registry: DynamicRouteRegistry = Depends(get_dynamic_route_registry),
    trino: TrinoClient = Depends(get_trino_client),
    pii_mapper: PiiMapper = Depends(get_pii_mapper),
) -> DynamicRouteService:
    return DynamicRouteService(
        registry=registry,
        trino=trino,
        pii_mapper=pii_mapper,
    )
