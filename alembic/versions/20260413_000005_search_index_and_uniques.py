from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260413_000005"
down_revision = "20260411_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_page_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("chunk_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_raw_page_chunks_page_id", "raw_page_chunks", ["page_id"], unique=False)
    op.create_index("uq_raw_page_chunks_page_chunk", "raw_page_chunks", ["page_id", "chunk_no"], unique=True)

    op.create_index("uq_pages_space_confluence_page", "pages", ["space_id", "confluence_page_id"], unique=True)
    op.create_index("uq_pages_space_slug", "pages", ["space_id", "slug"], unique=True)
    op.create_index("uq_page_versions_page_version", "page_versions", ["page_id", "version_number"], unique=True)
    op.create_index("uq_wiki_documents_page", "wiki_documents", ["page_id"], unique=True)
    op.create_index("uq_knowledge_documents_space_kind_slug", "knowledge_documents", ["space_id", "kind", "slug"], unique=True)
    op.create_index("uq_sync_cursors_space_cursor_type", "sync_cursors", ["space_id", "cursor_type"], unique=True)
    op.create_index(
        "ix_page_links_source_target_type",
        "page_links",
        ["source_page_id", "target_page_id", "link_type"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE VIRTUAL TABLE raw_page_chunks_fts
            USING fts5(content, content='raw_page_chunks', content_rowid='id', tokenize='unicode61')
            """
        )
        op.execute(
            """
            CREATE TRIGGER raw_page_chunks_ai AFTER INSERT ON raw_page_chunks BEGIN
              INSERT INTO raw_page_chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER raw_page_chunks_ad AFTER DELETE ON raw_page_chunks BEGIN
              INSERT INTO raw_page_chunks_fts(raw_page_chunks_fts, rowid, content)
              VALUES ('delete', old.id, old.content);
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER raw_page_chunks_au AFTER UPDATE ON raw_page_chunks BEGIN
              INSERT INTO raw_page_chunks_fts(raw_page_chunks_fts, rowid, content)
              VALUES ('delete', old.id, old.content);
              INSERT INTO raw_page_chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS raw_page_chunks_au")
        op.execute("DROP TRIGGER IF EXISTS raw_page_chunks_ad")
        op.execute("DROP TRIGGER IF EXISTS raw_page_chunks_ai")
        op.execute("DROP TABLE IF EXISTS raw_page_chunks_fts")

    op.drop_index("ix_page_links_source_target_type", table_name="page_links")
    op.drop_index("uq_sync_cursors_space_cursor_type", table_name="sync_cursors")
    op.drop_index("uq_knowledge_documents_space_kind_slug", table_name="knowledge_documents")
    op.drop_index("uq_wiki_documents_page", table_name="wiki_documents")
    op.drop_index("uq_page_versions_page_version", table_name="page_versions")
    op.drop_index("uq_pages_space_slug", table_name="pages")
    op.drop_index("uq_pages_space_confluence_page", table_name="pages")
    op.drop_index("uq_raw_page_chunks_page_chunk", table_name="raw_page_chunks")
    op.drop_index("ix_raw_page_chunks_page_id", table_name="raw_page_chunks")
    op.drop_table("raw_page_chunks")
