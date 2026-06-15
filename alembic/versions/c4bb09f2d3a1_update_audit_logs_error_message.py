"""update audit logs error message

Revision ID: c4bb09f2d3a1
Revises: 8f2d4a91c7b3
Create Date: 2026-06-15 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4bb09f2d3a1"
down_revision: str | None = "8f2d4a91c7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_request_id")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS request_id")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'denied_reason'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'error_message'
            ) THEN
                ALTER TABLE audit_logs RENAME COLUMN denied_reason TO error_message;
            ELSIF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'denied_reson'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'error_message'
            ) THEN
                ALTER TABLE audit_logs RENAME COLUMN denied_reson TO error_message;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'error_message'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'audit_logs'
                  AND column_name = 'denied_reason'
            ) THEN
                ALTER TABLE audit_logs RENAME COLUMN error_message TO denied_reason;
            END IF;
        END $$;
    """)
    op.add_column(
        "audit_logs",
        sa.Column("request_id", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
