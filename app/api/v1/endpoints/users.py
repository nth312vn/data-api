from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.services import get_authorization_service, get_user_service
from app.models.user import User, UserRole
from app.schemas.authorization import UserPermissionAssign, UserRoleAssign
from app.schemas.user import UserAdminCreate, UserAdminUpdate, UserRead, UserUpdate
from app.services.authorization import AuthorizationService
from app.services.user import UserService

router = APIRouter()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserAdminCreate,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.create_user(payload)


@router.get("", response_model=list[UserRead])
async def list_users(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> list[User]:
    return await service.list_users(limit=limit, offset=offset)


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.update_profile(current_user, payload)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete_account(current_user)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    payload: UserAdminUpdate,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.update_user(user_id, payload)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete_user(user_id)


@router.post("/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def assign_role(
    user_id: UUID,
    payload: UserRoleAssign,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> None:
    await service.assign_role(user_id=user_id, role_id=payload.role_id)


@router.delete("/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role(
    user_id: UUID,
    role_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> None:
    await service.remove_role(user_id=user_id, role_id=role_id)


@router.post("/{user_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
async def assign_permission(
    user_id: UUID,
    payload: UserPermissionAssign,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> None:
    await service.assign_permission(
        user_id=user_id,
        permission_id=payload.permission_id,
    )


@router.delete(
    "/{user_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_permission(
    user_id: UUID,
    permission_id: UUID,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> None:
    await service.remove_permission(
        user_id=user_id,
        permission_id=permission_id,
    )
