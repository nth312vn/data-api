"""add api permissions rbac

Revision ID: 8f2d4a91c7b3
Revises: fdda72aad25e
Create Date: 2026-06-10 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8f2d4a91c7b3"
down_revision: str | None = "fdda72aad25e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=320),
        nullable=True,
    )

    op.drop_index("ix_audit_logs_status", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.alter_column(
        "audit_logs",
        "actor_user_id",
        existing_type=sa.UUID(),
        nullable=True,
        new_column_name="user_id",
    )
    op.alter_column(
        "audit_logs",
        "payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        new_column_name="parameters",
    )
    op.add_column(
        "audit_logs", sa.Column("username", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "audit_logs", sa.Column("api_route", sa.String(length=500), nullable=True)
    )
    op.add_column("audit_logs", sa.Column("allowed", sa.Boolean(), nullable=True))
    op.add_column("audit_logs", sa.Column("denied_reason", sa.Text(), nullable=True))
    op.add_column(
        "audit_logs", sa.Column("time_process_ms", sa.Integer(), nullable=True)
    )
    op.add_column(
        "audit_logs", sa.Column("request_id", sa.String(length=100), nullable=True)
    )
    op.execute("""
        UPDATE audit_logs
        SET api_route = event_type,
            allowed = (status = 'success')
        """)
    op.alter_column(
        "audit_logs",
        "api_route",
        existing_type=sa.String(length=500),
        nullable=False,
    )
    op.alter_column(
        "audit_logs",
        "allowed",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.drop_column("audit_logs", "event_type")
    op.drop_column("audit_logs", "status")
    postgresql.ENUM(
        "success",
        "missing_mapping",
        "failed",
        name="audit_log_status",
    ).drop(op.get_bind(), checkfirst=True)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_api_route", "audit_logs", ["api_route"])
    op.create_index("ix_audit_logs_allowed", "audit_logs", ["allowed"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])

    op.create_table(
        "roles",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "api_permissions",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("route_prefix", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_api_permissions_route_prefix",
        "api_permissions",
        ["route_prefix"],
        unique=True,
    )
    op.create_index(
        op.f("ix_api_permissions_is_active"),
        "api_permissions",
        ["is_active"],
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_table(
        "user_api_permissions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("permission_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["api_permissions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "permission_id"),
    )


def downgrade() -> None:
    op.drop_table("user_api_permissions")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_api_permissions_is_active"), table_name="api_permissions")
    op.drop_index("uq_api_permissions_route_prefix", table_name="api_permissions")
    op.drop_table("api_permissions")
    op.drop_index("uq_roles_code", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_allowed", table_name="audit_logs")
    op.drop_index("ix_audit_logs_api_route", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    audit_log_status = postgresql.ENUM(
        "success",
        "missing_mapping",
        "failed",
        name="audit_log_status",
    )
    audit_log_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "audit_logs", sa.Column("event_type", sa.String(length=100), nullable=True)
    )
    op.add_column("audit_logs", sa.Column("status", audit_log_status, nullable=True))
    op.execute("""
        UPDATE audit_logs
        SET event_type = left(api_route, 100),
            status = CASE WHEN allowed THEN 'success'::audit_log_status
                          ELSE 'failed'::audit_log_status
                     END
        """)
    op.alter_column(
        "audit_logs",
        "event_type",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.alter_column(
        "audit_logs",
        "status",
        existing_type=audit_log_status,
        nullable=False,
    )
    op.alter_column(
        "audit_logs",
        "user_id",
        existing_type=sa.UUID(),
        nullable=True,
        new_column_name="actor_user_id",
    )
    op.alter_column(
        "audit_logs",
        "parameters",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        new_column_name="payload",
    )
    op.execute("UPDATE audit_logs SET payload = '{}'::jsonb WHERE payload IS NULL")
    op.alter_column(
        "audit_logs",
        "payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "time_process_ms")
    op.drop_column("audit_logs", "denied_reason")
    op.drop_column("audit_logs", "allowed")
    op.drop_column("audit_logs", "api_route")
    op.drop_column("audit_logs", "username")
    op.create_index(
        "ix_audit_logs_actor_user_id",
        "audit_logs",
        ["actor_user_id"],
    )
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_status", "audit_logs", ["status"])

    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=320),
        nullable=False,
    )
