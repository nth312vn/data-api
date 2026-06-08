"""create audit logs

Revision ID: 202606080002
Revises: 202606080001
Create Date: 2026-06-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202606080002"
down_revision: str | None = "202606080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    audit_log_status = sa.Enum(
        "success",
        "missing_mapping",
        "failed",
        name="audit_log_status",
    )
    audit_log_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", audit_log_status, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_actor_user_id",
        "audit_logs",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_event_type",
        "audit_logs",
        ["event_type"],
        unique=False,
    )
    op.create_index("ix_audit_logs_status", "audit_logs", ["status"], unique=False)

    op.execute(
        """
        CREATE TRIGGER audit_logs_set_updated_at
        BEFORE UPDATE ON audit_logs
        FOR EACH ROW
        EXECUTE PROCEDURE set_updated_at();
        """,
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_set_updated_at ON audit_logs")
    op.drop_index("ix_audit_logs_status", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    sa.Enum(name="audit_log_status").drop(op.get_bind(), checkfirst=True)
