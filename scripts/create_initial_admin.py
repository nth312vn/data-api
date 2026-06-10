import asyncio
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from app.models.user import UserRole
from app.repositories.sqlalchemy.authorization import SQLAlchemyAuthorizationRepository
from app.repositories.sqlalchemy.user import SQLAlchemyUserRepository
from app.schemas.user import UserAdminCreate, UserAdminUpdate
from app.services.user import UserService

DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_FULL_NAME = "Initial Admin"


async def create_initial_admin() -> None:
    settings = get_settings()
    password = secrets.token_urlsafe(24)

    async with AsyncSessionFactory() as session:
        users = SQLAlchemyUserRepository(session)
        authorization = SQLAlchemyAuthorizationRepository(session)
        existing_admin = await users.get_admin_user()
        if existing_admin is not None:
            print(f"Admin user already exists: {existing_admin.email}; skipping init")
            return

        service = UserService(
            users=users,
            authorization=authorization,
            uow=SQLAlchemyUnitOfWork(session),
            settings=settings,
        )

        existing_user = await users.get_by_email(DEFAULT_ADMIN_EMAIL)
        if existing_user is None:
            existing_user = await users.get_by_username(DEFAULT_ADMIN_USERNAME)

        if existing_user is None:
            admin = await service.create_user(
                UserAdminCreate(
                    email=DEFAULT_ADMIN_EMAIL,
                    username=DEFAULT_ADMIN_USERNAME,
                    password=password,
                    full_name=DEFAULT_ADMIN_FULL_NAME,
                    role=UserRole.admin,
                    is_active=True,
                ),
            )
            print(f"Created initial admin user: {admin.email}")
        else:
            admin = await service.update_user(
                existing_user.id,
                UserAdminUpdate(
                    password=password,
                    role=UserRole.admin,
                    is_active=True,
                    full_name=existing_user.full_name or DEFAULT_ADMIN_FULL_NAME,
                ),
            )
            print(f"Promoted existing user to initial admin: {admin.email}")

        print(f"Initial admin username: {admin.username}")
        print(f"Initial admin temporary password: {password}")


async def main() -> None:
    try:
        await create_initial_admin()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
