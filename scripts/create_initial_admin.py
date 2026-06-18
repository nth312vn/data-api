import asyncio
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.infrastructure.database.session import (  # noqa: E402
    AsyncSessionFactory,
    engine,
)
from app.infrastructure.database.unit_of_work import (  # noqa: E402
    SQLAlchemyUnitOfWork,
)
from app.models.user import UserRole  # noqa: E402
from app.repositories.sqlalchemy.user import (  # noqa: E402
    SQLAlchemyUserRepository,
)
from app.schemas.user import UserAdminCreate, UserAdminUpdate  # noqa: E402
from app.services.user import UserService  # noqa: E402

DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_USERNAME = "admin"


async def create_initial_admin() -> None:
    settings = get_settings()
    password = secrets.token_urlsafe(24)

    async with AsyncSessionFactory() as session:
        users = SQLAlchemyUserRepository(session)
        existing_admin = await users.get_admin_user()
        if existing_admin is not None:
            print(f"Admin user already exists: {existing_admin.email}; skipping init")
            return

        service = UserService(
            users=users,
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
                    role=UserRole.admin,
                ),
            )
            print(f"Created initial admin user: {admin.email}")
        else:
            admin = await service.update_user(
                existing_user.id,
                UserAdminUpdate(
                    password=password,
                    role=UserRole.admin,
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
