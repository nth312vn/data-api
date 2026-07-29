"""create dynamic routes

Revision ID: 7d31b2f4a9c0
Revises: 2d7c9a4e1b63
Create Date: 2026-07-29 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7d31b2f4a9c0"
down_revision: str | None = "2d7c9a4e1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dynamic_routes",
        sa.Column("prefix", sa.String(length=50), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column("original_sql", sa.Text(), nullable=False),
        sa.Column("canonical_sql", sa.Text(), nullable=False),
        sa.Column(
            "parameter_definitions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "path <> ''",
            name="ck_dynamic_routes_path_not_empty",
        ),
        sa.CheckConstraint(
            "path NOT LIKE '/%' AND path NOT LIKE '%/'",
            name="ck_dynamic_routes_path_relative",
        ),
        sa.CheckConstraint(
            "position('//' in path) = 0",
            name="ck_dynamic_routes_path_segments",
        ),
        sa.CheckConstraint(
            "prefix = lower(prefix)",
            name="ck_dynamic_routes_prefix_lower",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prefix",
            "path",
            name="uq_dynamic_routes_prefix_path",
        ),
    )
    op.create_index(
        "ix_dynamic_routes_created_by",
        "dynamic_routes",
        ["created_by"],
    )
    op.create_index(
        "ix_dynamic_routes_prefix",
        "dynamic_routes",
        ["prefix"],
    )
    op.create_index(
        "ix_dynamic_routes_updated_at",
        "dynamic_routes",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dynamic_routes_updated_at",
        table_name="dynamic_routes",
    )
    op.drop_index(
        "ix_dynamic_routes_prefix",
        table_name="dynamic_routes",
    )
    op.drop_index(
        "ix_dynamic_routes_created_by",
        table_name="dynamic_routes",
    )
    op.drop_table("dynamic_routes")
