from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260411_000004"
down_revision = "20260407_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lock_name", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.String(length=100), nullable=False),
        sa.Column("holder_kind", sa.String(length=50), nullable=False),
        sa.Column("holder_scope", sa.String(length=255), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sync_leases_lock_name", "sync_leases", ["lock_name"], unique=True)
    op.create_index("ix_sync_leases_owner_id", "sync_leases", ["owner_id"], unique=False)
    op.create_index("ix_sync_leases_expires_at", "sync_leases", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sync_leases_expires_at", table_name="sync_leases")
    op.drop_index("ix_sync_leases_owner_id", table_name="sync_leases")
    op.drop_index("ix_sync_leases_lock_name", table_name="sync_leases")
    op.drop_table("sync_leases")
