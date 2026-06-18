import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token
from app.dependencies.database import get_unit_of_work
from app.dependencies.repositories import (
    get_audit_log_repository,
    get_user_repository,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.user import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    payload = decode_token(token, settings=settings, expected_type="access")
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise AuthenticationError("Invalid token subject")

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise AuthenticationError("Invalid token subject") from exc

    user = await users.get_by_id(user_id)
    if user is None:
        raise AuthenticationError("Invalid authentication credentials")

    return user


def require_roles(*allowed_roles: UserRole) -> Callable[..., object]:
    async def dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise AuthorizationError()
        return current_user

    return dependency


async def require_api_permission(
    request: Request,
    current_user: User = Depends(get_current_user),
    audit_logs: AuditLogRepository = Depends(get_audit_log_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> User:
    started_at = time.perf_counter()
    route_path = _normalize_route_path(
        request.url.path,
        api_v1_prefix=settings.api_v1_prefix,
    )
    allowed, error_message = await check_api_permission(
        user=current_user,
        route_path=route_path,
    )
    elapsed_ms = _elapsed_ms(started_at)

    await _write_api_permission_audit_log(
        request=request,
        audit_logs=audit_logs,
        uow=uow,
        current_user=current_user,
        allowed=allowed,
        error_message=error_message,
        time_process_ms=elapsed_ms,
    )

    if not allowed:
        raise AuthorizationError(error_message or "API permission denied")

    return current_user


async def check_api_permission(
    *,
    user: User,
    route_path: str,
) -> tuple[bool, str | None]:
    if user.role == UserRole.admin:
        return True, None

    if _route_matches_username(route_path, user.username):
        return True, None
    return False, "API permission denied"


def _route_matches_username(route_path: str, username: str) -> bool:
    normalized_path = route_path.rstrip("/") or "/"
    username_prefix = f"/{username.lower()}"
    return normalized_path == username_prefix or normalized_path.startswith(
        f"{username_prefix}/",
    )


async def _write_api_permission_audit_log(
    *,
    request: Request,
    audit_logs: AuditLogRepository,
    uow: UnitOfWork,
    current_user: User,
    allowed: bool,
    error_message: str | None,
    time_process_ms: int,
) -> None:
    await audit_logs.create(
        AuditLog(
            user_id=current_user.id,
            username=current_user.username,
            api_route=request.url.path,
            parameters=_request_parameters(request),
            allowed=allowed,
            error_message=error_message,
            time_process_ms=time_process_ms,
        ),
    )
    await uow.commit()


def _request_parameters(request: Request) -> dict[str, Any]:
    return dict(request.query_params)


def _normalize_route_path(path: str, *, api_v1_prefix: str) -> str:
    prefix = api_v1_prefix.rstrip("/")
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return path.rstrip("/") or "/"


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)
