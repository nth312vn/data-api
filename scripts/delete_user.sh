#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python - "$@" <<'PY'
import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from app.models.user import User
from app.repositories.sqlalchemy.user import SQLAlchemyUserRepository
from app.services.user import UserService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete an application user.",
    )
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument(
        "--username",
        help="Username of the user to delete.",
    )
    identity.add_argument(
        "--email",
        help="Email of the user to delete.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation.",
    )
    return parser.parse_args()


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


def confirm_delete(user: User, *, confirmed: bool) -> None:
    if confirmed:
        return

    print(f"User ID: {user.id}")
    print(f"Username: {user.username}")
    print(f"Email: {user.email or ''}")
    print(f"Role: {user.role.value}")
    expected = user.username
    typed = input(f"Type '{expected}' to delete this user: ")
    if typed != expected:
        raise ValueError("delete confirmation did not match username")


async def delete_user(args: argparse.Namespace) -> dict[str, str]:
    settings = get_settings()

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

        confirm_delete(user, confirmed=bool(args.yes))
        deleted_user = {
            "id": str(user.id),
            "email": user.email or "",
            "username": user.username,
            "role": user.role.value,
        }
        await service.delete_user(user.id)
        return deleted_user


async def async_main() -> int:
    try:
        user = await delete_user(parse_args())
    except (AppError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"Deleted user: {user['username']}")
    print(f"User ID: {user['id']}")
    print(f"Email: {user['email']}")
    print(f"Role: {user['role']}")
    return 0


raise SystemExit(asyncio.run(async_main()))
PY
