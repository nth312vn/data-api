from fastapi import APIRouter, Depends

from app.dependencies.auth import require_roles
from app.dependencies.services import get_authorization_service
from app.models.authorization import Role
from app.models.user import User, UserRole
from app.schemas.authorization import RoleRead
from app.services.authorization import AuthorizationService

router = APIRouter()


@router.get("", response_model=list[RoleRead])
async def list_roles(
    _admin: User = Depends(require_roles(UserRole.admin)),
    service: AuthorizationService = Depends(get_authorization_service),
) -> list[Role]:
    return await service.list_roles()
