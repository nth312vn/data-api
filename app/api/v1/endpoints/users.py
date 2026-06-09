from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.services import get_user_service
from app.models.user import User, UserRole
from app.schemas.user import UserAdminCreate, UserAdminUpdate, UserRead, UserUpdate
from app.services.user import UserService

router = APIRouter()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserAdminCreate,
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: UserService = Depends(get_user_service),
) -> User:
    return await service.create_user(payload)


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
