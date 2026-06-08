from collections.abc import Callable
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token
from app.dependencies.repositories import get_user_repository
from app.models.user import User, UserRole
from app.repositories.interfaces.user import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise AuthorizationError()
        return current_user

    return dependency
