from uuid import uuid4

import pytest

from app.dependencies.auth import check_api_permission
from app.models.user import User, UserRole


def make_user(*, username: str, role: UserRole = UserRole.user) -> User:
    return User(
        id=uuid4(),
        email=None,
        username=username,
        hashed_password="hash",
        role=role,
    )


@pytest.mark.asyncio
async def test_admin_can_access_any_api_prefix() -> None:
    allowed, error = await check_api_permission(
        user=make_user(username="admin", role=UserRole.admin),
        route_path="/power_bi/deeplink_1",
    )

    assert allowed
    assert error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("route_path", ["/power_bi", "/power_bi/deeplink_1"])
async def test_user_can_access_matching_api_prefix(route_path: str) -> None:
    allowed, error = await check_api_permission(
        user=make_user(username="power_bi"),
        route_path=route_path,
    )

    assert allowed
    assert error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("route_path", ["/data/users", "/power_bi_extra"])
async def test_user_cannot_access_other_or_similar_prefix(route_path: str) -> None:
    allowed, error = await check_api_permission(
        user=make_user(username="power_bi"),
        route_path=route_path,
    )

    assert not allowed
    assert error == "API permission denied"
