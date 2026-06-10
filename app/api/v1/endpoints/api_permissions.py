from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_authorization_service
from app.models.authorization import ApiPermission
from app.models.user import User, UserRole
from app.schemas.authorization import (
    ApiPermissionCreate,
    ApiPermissionRead,
    ApiPermissionUpdate,
)
from app.services.authorization import AuthorizationService

router = APIRouter()


@router.post("", response_model=ApiPermissionRead, status_code=status.HTTP_201_CREATED)
async def create_permission(
    payload: ApiPermissionCreate,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> ApiPermission:
    return await service.create_permission(payload)


@router.get("", response_model=list[ApiPermissionRead])
async def list_permissions(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> list[ApiPermission]:
    return await service.list_permissions(limit=limit, offset=offset)


@router.get("/{permission_id}", response_model=ApiPermissionRead)
async def get_permission(
    permission_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> ApiPermission:
    return await service.get_permission(permission_id)


@router.patch("/{permission_id}", response_model=ApiPermissionRead)
async def update_permission(
    permission_id: UUID,
    payload: ApiPermissionUpdate,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> ApiPermission:
    return await service.update_permission(permission_id, payload)


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> None:
    await service.delete_permission(permission_id)
