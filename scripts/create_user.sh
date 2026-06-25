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
from app.models.user import User, UserRole
from app.repositories.sqlalchemy.user import SQLAlchemyUserRepository
from app.schemas.user import UserAdminCreate, UserAdminUpdate
from app.services.user import UserService

DEFAULT_PASSWORD_ENV = "CREATE_USER_PASSWORD"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update an application user.",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Username used for login and route authorization.",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Optional user email.",
    )
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.user.value,
        help="User role to assign.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Password to set. Prefer --password-env in shared shells.",
    )
    parser.add_argument(
        "--password-env",
        default=DEFAULT_PASSWORD_ENV,
        help=(
            "Environment variable containing the password. "
            f"Defaults to {DEFAULT_PASSWORD_ENV}."
        ),
    )
    return parser.parse_args()


def password_from_args(args: argparse.Namespace) -> str | None:
    if args.password:
        return str(args.password)
    password = os.getenv(str(args.password_env))
    if password is None or password == "":
        return None
    return password


async def get_existing_user(
    users: SQLAlchemyUserRepository,
    *,
    username: str,
    email: str | None,
) -> User | None:
    username_user = await users.get_by_username(username)
    if email is None:
        return username_user

    email_user = await users.get_by_email(email)
    if (
        username_user is not None
        and email_user is not None
        and username_user.id != email_user.id
    ):
        raise ValueError("username and email belong to different users")

    return username_user or email_user


async def create_or_update_user(
    args: argparse.Namespace,
) -> tuple[User, str | None, bool]:
    settings = get_settings()
    username = str(args.username).strip().lower()
    email = str(args.email).strip().lower() if args.email else None
    role = UserRole(str(args.role))
    password = password_from_args(args)
    generated_password: str | None = None

    async with AsyncSessionFactory() as session:
        users = SQLAlchemyUserRepository(session)
        service = UserService(
            users=users,
            uow=SQLAlchemyUnitOfWork(session),
            settings=settings,
        )
        existing_user = await get_existing_user(
            users,
            username=username,
            email=email,
        )

        if existing_user is None:
            if password is None:
                password = secrets.token_urlsafe(24)
                generated_password = password
            user = await service.create_user(
                UserAdminCreate(
                    email=email,
                    username=username,
                    password=password,
                    role=role,
                ),
            )
            return user, generated_password, True

        update_values: dict[str, object] = {
            "username": username,
            "role": role,
        }
        if email is not None:
            update_values["email"] = email
        if password is not None:
            update_values["password"] = password

        user = await service.update_user(
            existing_user.id,
            UserAdminUpdate(**update_values),
        )
        return user, generated_password, False


async def async_main() -> int:
    try:
        user, generated_password, created = await create_or_update_user(parse_args())
    except (AppError, ValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    action = "Created" if created else "Updated"
    print(f"{action} user: {user.username}")
    print(f"User ID: {user.id}")
    print(f"Username: {user.username}")
    print(f"Email: {user.email or ''}")
    print(f"Role: {user.role.value}")
    if generated_password is not None:
        print(f"Temporary password: {generated_password}")
    return 0


raise SystemExit(asyncio.run(async_main()))
PY
