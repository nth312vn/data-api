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
    get_authorization_repository,
    get_user_repository,
)
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.interfaces.audit_log import AuditLogRepository
from app.repositories.interfaces.authorization import AuthorizationRepository
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
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid authentication credentials")

    return user


def require_roles(*allowed_roles: UserRole) -> Callable[..., object]:
    async def dependency(
        current_user: User = Depends(get_current_user),
        authorization: AuthorizationRepository = Depends(get_authorization_repository),
    ) -> User:
        allowed = {role.value for role in allowed_roles}
        role_codes = set(await authorization.get_user_role_codes(current_user.id))
        role_codes.add(current_user.role.value)
        if not role_codes.intersection(allowed):
            raise AuthorizationError()
        return current_user

    return dependency


async def require_api_permission(
    request: Request,
    current_user: User = Depends(get_current_user),
    authorization: AuthorizationRepository = Depends(get_authorization_repository),
    audit_logs: AuditLogRepository = Depends(get_audit_log_repository),
    uow: UnitOfWork = Depends(get_unit_of_work),
    settings: Settings = Depends(get_settings),
) -> User:
    started_at = time.perf_counter()
    route_path = _normalize_route_path(
        request.url.path,
        api_v1_prefix=settings.api_v1_prefix,
    )
    allowed, denied_reason = await check_api_permission(
        user=current_user,
        route_path=route_path,
        authorization=authorization,
    )
    elapsed_ms = _elapsed_ms(started_at)

    await _write_api_permission_audit_log(
        request=request,
        audit_logs=audit_logs,
        uow=uow,
        current_user=current_user,
        allowed=allowed,
        denied_reason=denied_reason,
        time_process_ms=elapsed_ms,
    )

    if not allowed:
        raise AuthorizationError(denied_reason or "API permission denied")

    return current_user


async def check_api_permission(
    *,
    user: User,
    route_path: str,
    authorization: AuthorizationRepository,
) -> tuple[bool, str | None]:
    role_codes = set(await authorization.get_user_role_codes(user.id))
    role_codes.add(user.role.value)
    if UserRole.admin.value in role_codes:
        return True, None

    allowed = await authorization.user_has_permission_for_route(
        user_id=user.id,
        route_path=route_path,
    )
    if allowed:
        return True, None
    return False, "API permission denied"


async def _write_api_permission_audit_log(
    *,
    request: Request,
    audit_logs: AuditLogRepository,
    uow: UnitOfWork,
    current_user: User,
    allowed: bool,
    denied_reason: str | None,
    time_process_ms: int,
) -> None:
    await audit_logs.create(
        AuditLog(
            user_id=current_user.id,
            username=current_user.username,
            api_route=request.url.path,
            parameters=_request_parameters(request),
            allowed=allowed,
            denied_reason=denied_reason,
            time_process_ms=time_process_ms,
            request_id=_get_request_id(request),
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


def _get_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    return request.headers.get("X-Request-ID")


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)
