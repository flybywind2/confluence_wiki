from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260407_000002"
down_revision = "20260406_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("page_versions", sa.Column("markdown_path", sa.String(length=1000), nullable=True))
    op.add_column("page_versions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("page_versions", sa.Column("source_updated_at", sa.DateTime(), nullable=True))
    op.add_column("page_versions", sa.Column("created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("page_versions", "created_at")
    op.drop_column("page_versions", "source_updated_at")
    op.drop_column("page_versions", "summary")
    op.drop_column("page_versions", "markdown_path")
