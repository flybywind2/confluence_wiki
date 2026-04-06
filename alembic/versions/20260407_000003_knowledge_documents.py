from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260407_000003"
down_revision = "20260407_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("slug", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("markdown_path", sa.String(length=1000), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("source_refs", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_documents_space_id", "knowledge_documents", ["space_id"], unique=False)
    op.create_index("ix_knowledge_documents_kind", "knowledge_documents", ["kind"], unique=False)
    op.create_index("ix_knowledge_documents_slug", "knowledge_documents", ["slug"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_slug", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_kind", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_space_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
