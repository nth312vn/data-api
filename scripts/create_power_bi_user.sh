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
from app.models.user import User, UserRole

DEFAULT_USERNAME = "power_bi"
DEFAULT_EMAIL = "power_bi@example.com"


def getenv(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


async def get_user(session, *, username: str, email: str | None) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    username_user = result.scalar_one_or_none()
    if email is None:
        return username_user

    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    email_user = result.scalar_one_or_none()
    if (
        username_user is not None
        and email_user is not None
        and username_user.id != email_user.id
    ):
        raise ValueError("POWER_BI_USERNAME and POWER_BI_EMAIL belong to different users")
    return username_user or email_user


async def ensure_power_bi_user() -> None:
    settings = get_settings()
    username = getenv("POWER_BI_USERNAME", DEFAULT_USERNAME).lower()
    email = getenv("POWER_BI_EMAIL", DEFAULT_EMAIL).lower()

    configured_password = os.getenv("POWER_BI_PASSWORD")
    if configured_password is not None and 0 < len(configured_password) < 12:
        raise ValueError("POWER_BI_PASSWORD must be at least 12 characters")

    async with AsyncSessionFactory() as session:
        user = await get_user(session, username=username, email=email)
        generated_password: str | None = None
        if user is None:
            password = configured_password
            if not password:
                password = secrets.token_urlsafe(24)
                generated_password = password
            user = User(
                email=email,
                username=username,
                hashed_password=hash_password(
                    password,
                    rounds=settings.password_bcrypt_rounds,
                ),
                role=UserRole.user,
            )
            session.add(user)
            print(f"Created user: {user.username}")
        else:
            user.username = username
            user.email = email
            user.role = UserRole.user
            if configured_password:
                user.hashed_password = hash_password(
                    configured_password,
                    rounds=settings.password_bcrypt_rounds,
                )
                print(f"Updated password for existing user: {user.username}")
            else:
                print(f"User already exists: {user.username}")

        await session.commit()

    print(f"Username: {user.username}")
    print(f"Email: {user.email}")
    print(f"API prefix: /{user.username}")
    if generated_password is not None:
        print(f"Temporary password: {generated_password}")


async def main() -> None:
    try:
        await ensure_power_bi_user()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
PY
