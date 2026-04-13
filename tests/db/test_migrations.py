from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_upgrade_runs_against_sqlite(tmp_path):
    db_path = tmp_path / "app.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    assert db_path.exists()
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        tables = set(
            conn.execute(
                text("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
            ).scalars()
        )
        indexes = set(
            conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name")
            ).scalars()
        )
    assert "raw_page_chunks" in tables
    assert "raw_page_chunks_fts" in tables
    assert "uq_pages_space_confluence_page" in indexes
    assert "uq_knowledge_documents_space_kind_slug" in indexes
