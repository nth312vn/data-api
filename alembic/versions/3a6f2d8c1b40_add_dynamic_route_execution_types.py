"""add dynamic route execution types

Revision ID: 3a6f2d8c1b40
Revises: 7d31b2f4a9c0
Create Date: 2026-08-03 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3a6f2d8c1b40"
down_revision: str | None = "7d31b2f4a9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    db_type = postgresql.ENUM(
        "trino",
        "postgres",
        name="dynamic_route_db_type",
    )
    pii_type = postgresql.ENUM(
        "account_id",
        "customer_id",
        name="dynamic_route_pii_type",
    )
    response_type = postgresql.ENUM(
        "paginated",
        "data",
        name="dynamic_route_response_type",
    )
    db_type.create(bind, checkfirst=True)
    pii_type.create(bind, checkfirst=True)
    response_type.create(bind, checkfirst=True)

    op.add_column(
        "dynamic_routes",
        sa.Column(
            "db_type",
            postgresql.ENUM(
                "trino",
                "postgres",
                name="dynamic_route_db_type",
                create_type=False,
            ),
            server_default="trino",
            nullable=False,
        ),
    )
    op.add_column(
        "dynamic_routes",
        sa.Column(
            "pii_type",
            postgresql.ENUM(
                "account_id",
                "customer_id",
                name="dynamic_route_pii_type",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "dynamic_routes",
        sa.Column(
            "response_type",
            postgresql.ENUM(
                "paginated",
                "data",
                name="dynamic_route_response_type",
                create_type=False,
            ),
            server_default="data",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("dynamic_routes", "response_type")
    op.drop_column("dynamic_routes", "pii_type")
    op.drop_column("dynamic_routes", "db_type")

    bind = op.get_bind()
    postgresql.ENUM(name="dynamic_route_response_type").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(name="dynamic_route_pii_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="dynamic_route_db_type").drop(bind, checkfirst=True)
