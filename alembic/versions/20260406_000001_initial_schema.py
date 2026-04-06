from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260406_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("space_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("root_page_id", sa.String(length=64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_bootstrap_at", sa.DateTime()),
        sa.Column("last_incremental_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_spaces_space_key", "spaces", ["space_key"], unique=True)

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("confluence_page_id", sa.String(length=64), nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("parent_confluence_page_id", sa.String(length=64)),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("slug", sa.String(length=500), nullable=False),
        sa.Column("prod_url", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at_remote", sa.DateTime()),
        sa.Column("updated_at_remote", sa.DateTime()),
        sa.Column("last_synced_at", sa.DateTime()),
    )
    op.create_index("ix_pages_confluence_page_id", "pages", ["confluence_page_id"], unique=False)
    op.create_index("ix_pages_space_id", "pages", ["space_id"], unique=False)
    op.create_index("ix_pages_slug", "pages", ["slug"], unique=False)

    op.create_table(
        "page_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("body_hash", sa.String(length=128), nullable=False),
        sa.Column("source_excerpt_hash", sa.String(length=128), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_page_versions_page_id", "page_versions", ["page_id"], unique=False)

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("confluence_attachment_id", sa.String(length=64)),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255)),
        sa.Column("local_path", sa.String(length=1000), nullable=False),
        sa.Column("body_path", sa.String(length=1000)),
        sa.Column("is_image", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vlm_status", sa.String(length=50), nullable=False),
        sa.Column("vlm_summary", sa.Text()),
        sa.Column("downloaded_at", sa.DateTime()),
    )
    op.create_index("ix_assets_page_id", "assets", ["page_id"], unique=False)

    op.create_table(
        "page_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_page_id", sa.Integer(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("target_page_id", sa.Integer(), sa.ForeignKey("pages.id")),
        sa.Column("target_title", sa.String(length=500)),
        sa.Column("link_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_page_links_source_page_id", "page_links", ["source_page_id"], unique=False)
    op.create_index("ix_page_links_target_page_id", "page_links", ["target_page_id"], unique=False)

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("spaces.id")),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("processed_pages", sa.Integer(), nullable=False),
        sa.Column("processed_assets", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
    )

    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("spaces.id"), nullable=False),
        sa.Column("cursor_type", sa.String(length=50), nullable=False),
        sa.Column("cursor_value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sync_cursors_space_id", "sync_cursors", ["space_id"], unique=False)

    op.create_table(
        "wiki_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("markdown_path", sa.String(length=1000), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("index_line", sa.Text()),
        sa.Column("rendered_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_wiki_documents_page_id", "wiki_documents", ["page_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wiki_documents_page_id", table_name="wiki_documents")
    op.drop_table("wiki_documents")
    op.drop_index("ix_sync_cursors_space_id", table_name="sync_cursors")
    op.drop_table("sync_cursors")
    op.drop_table("sync_runs")
    op.drop_index("ix_page_links_target_page_id", table_name="page_links")
    op.drop_index("ix_page_links_source_page_id", table_name="page_links")
    op.drop_table("page_links")
    op.drop_index("ix_assets_page_id", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_page_versions_page_id", table_name="page_versions")
    op.drop_table("page_versions")
    op.drop_index("ix_pages_slug", table_name="pages")
    op.drop_index("ix_pages_space_id", table_name="pages")
    op.drop_index("ix_pages_confluence_page_id", table_name="pages")
    op.drop_table("pages")
    op.drop_index("ix_spaces_space_key", table_name="spaces")
    op.drop_table("spaces")
