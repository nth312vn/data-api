#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python - "$@" <<'PY'
import argparse
import asyncio
import os
import secrets
import sys

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from app.models.user import User
from app.repositories.sqlalchemy.user import SQLAlchemyUserRepository
from app.schemas.user import UserAdminUpdate
from app.services.user import UserService

DEFAULT_PASSWORD_ENV = "RESET_USER_PASSWORD"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset an application user's password.",
    )
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument(
        "--username",
        help="Username of the user to reset.",
    )
    identity.add_argument(
        "--email",
        help="Email of the user to reset.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="New password. Prefer --password-env in shared shells.",
    )
    parser.add_argument(
        "--password-env",
        default=DEFAULT_PASSWORD_ENV,
        help=(
            "Environment variable containing the new password. "
            f"Defaults to {DEFAULT_PASSWORD_ENV}."
        ),
    )
    return parser.parse_args()


def password_from_args(args: argparse.Namespace) -> tuple[str, bool]:
    if args.password:
        return str(args.password), False

    password = os.getenv(str(args.password_env))
    if password is not None and password != "":
        return password, False

    return secrets.token_urlsafe(24), True


async def get_user(
    users: SQLAlchemyUserRepository,
    *,
    username: str | None,
    email: str | None,
) -> User | None:
    if username is not None:
        return await users.get_by_username(username.strip().lower())
    if email is not None:
        return await users.get_by_email(email.strip().lower())
    return None


async def reset_password(args: argparse.Namespace) -> tuple[User, str, bool]:
    settings = get_settings()
    password, generated = password_from_args(args)

    async with AsyncSessionFactory() as session:
        users = SQLAlchemyUserRepository(session)
        service = UserService(
            users=users,
            uow=SQLAlchemyUnitOfWork(session),
            settings=settings,
        )
        user = await get_user(
            users,
            username=args.username,
            email=args.email,
        )
        if user is None:
            raise ValueError("user not found")

        updated = await service.update_user(
            user.id,
            UserAdminUpdate(password=password),
        )
        return updated, password, generated


async def async_main() -> int:
    try:
        user, password, generated = await reset_password(parse_args())
    except (AppError, ValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"Reset password for user: {user.username}")
    print(f"User ID: {user.id}")
    print(f"Username: {user.username}")
    print(f"Email: {user.email or ''}")
    if generated:
        print(f"Temporary password: {password}")
    return 0


raise SystemExit(asyncio.run(async_main()))
PY
