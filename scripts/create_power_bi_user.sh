#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import asyncio
import os
import secrets

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.models.authorization import ApiPermission, UserApiPermission
from app.models.user import User, UserRole

DEFAULT_USERNAME = "power_bi_user"
DEFAULT_EMAIL = "power_bi_user@example.com"
DEFAULT_FULL_NAME = "Power BI User"
DEFAULT_ROUTE_PREFIX = "/power_bi"


def getenv(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


async def get_user(session, *, username: str, email: str | None) -> User | None:
    stmt = select(User).where(User.username == username.lower())
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None or email is None:
        return user

    stmt = select(User).where(User.email == email.lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_power_bi_user() -> None:
    settings = get_settings()
    username = getenv("POWER_BI_USERNAME", DEFAULT_USERNAME).lower()
    email = getenv("POWER_BI_EMAIL", DEFAULT_EMAIL).lower()
    full_name = getenv("POWER_BI_FULL_NAME", DEFAULT_FULL_NAME)
    route_prefix = (
        getenv("POWER_BI_ROUTE_PREFIX", DEFAULT_ROUTE_PREFIX).rstrip("/") or "/"
    )
    if not route_prefix.startswith("/"):
        raise ValueError("POWER_BI_ROUTE_PREFIX must start with '/'")

    password = os.getenv("POWER_BI_PASSWORD")
    generated_password = password is None or password == ""
    if generated_password:
        password = secrets.token_urlsafe(24)
    if len(password) < 12:
        raise ValueError("POWER_BI_PASSWORD must be at least 12 characters")

    async with AsyncSessionFactory() as session:
        user = await get_user(session, username=username, email=email)
        if user is None:
            user = User(
                email=email,
                username=username,
                hashed_password=hash_password(
                    password,
                    rounds=settings.password_bcrypt_rounds,
                ),
                full_name=full_name,
                is_active=True,
                role=UserRole.user,
            )
            session.add(user)
            await session.flush()
            print(f"Created user: {user.username}")
        else:
            user.is_active = True
            user.role = UserRole.user
            if user.full_name is None:
                user.full_name = full_name
            if not generated_password:
                user.hashed_password = hash_password(
                    password,
                    rounds=settings.password_bcrypt_rounds,
                )
                print(f"Updated password for existing user: {user.username}")
            else:
                print(f"User already exists: {user.username}")

        stmt = select(ApiPermission).where(ApiPermission.route_prefix == route_prefix)
        result = await session.execute(stmt)
        permission = result.scalar_one_or_none()
        if permission is None:
            permission = ApiPermission(
                name="Power BI",
                description="Access to Power BI API routes",
                route_prefix=route_prefix,
                is_active=True,
            )
            session.add(permission)
            await session.flush()
            print(f"Created API permission: {permission.route_prefix}")
        else:
            permission.is_active = True
            print(f"API permission already exists: {permission.route_prefix}")

        stmt = select(UserApiPermission).where(
            UserApiPermission.user_id == user.id,
            UserApiPermission.permission_id == permission.id,
        )
        result = await session.execute(stmt)
        assignment = result.scalar_one_or_none()
        if assignment is None:
            session.add(
                UserApiPermission(user_id=user.id, permission_id=permission.id),
            )
            print(f"Assigned {permission.route_prefix} access to: {user.username}")
        else:
            print(f"{user.username} already has {permission.route_prefix} access")

        await session.commit()

    print(f"Username: {user.username}")
    print(f"Email: {user.email}")
    if generated_password:
        print(f"Temporary password: {password}")


async def main() -> None:
    try:
        await ensure_power_bi_user()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
PY
