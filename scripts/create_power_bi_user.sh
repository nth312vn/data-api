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
    user = result.scalar_one_or_none()
    if user is not None or email is None:
        return user

    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_power_bi_user() -> None:
    settings = get_settings()
    username = getenv("POWER_BI_USERNAME", DEFAULT_USERNAME).lower()
    email = getenv("POWER_BI_EMAIL", DEFAULT_EMAIL).lower()

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
                role=UserRole.user,
            )
            session.add(user)
            print(f"Created user: {user.username}")
        else:
            user.username = username
            user.email = email
            user.role = UserRole.user
            if not generated_password:
                user.hashed_password = hash_password(
                    password,
                    rounds=settings.password_bcrypt_rounds,
                )
                print(f"Updated password for existing user: {user.username}")
            else:
                print(f"User already exists: {user.username}")

        await session.commit()

    print(f"Username: {user.username}")
    print(f"Email: {user.email}")
    print(f"API prefix: /{user.username}")
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
