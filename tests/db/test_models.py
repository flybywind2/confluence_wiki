from sqlalchemy import create_engine

from app.db.base import Base


def test_metadata_contains_core_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert "spaces" in Base.metadata.tables
    assert "pages" in Base.metadata.tables
    assert "knowledge_documents" in Base.metadata.tables
    assert "page_links" in Base.metadata.tables
    assert "sync_runs" in Base.metadata.tables
