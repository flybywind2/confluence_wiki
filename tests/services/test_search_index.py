from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models import Page
from app.db.session import create_session_factory
from app.demo_seed import seed_demo_content
from app.services.search_index import SearchIndexService


def test_search_index_reindexes_pages_and_returns_fts_candidates(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = SearchIndexService(settings)
    session_factory = create_session_factory(settings.database_url)
    session = session_factory()
    try:
        indexed = service.reindex_pages(session)
        session.commit()
        candidate_ids = service.find_candidate_page_ids(session, query="운영 대시보드", selected_space="DEMO", limit=5)
        matched_pages = session.scalars(select(Page).where(Page.id.in_(candidate_ids))).all()
    finally:
        session.close()

    assert indexed >= 4
    assert candidate_ids
    assert any(page.slug == "ops-dashboard-9002" for page in matched_pages)


def test_search_index_fts_objects_exist_after_upgrade(tmp_path, sample_settings_dict):
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    service = SearchIndexService(settings)
    session_factory = create_session_factory(settings.database_url)
    session = session_factory()
    try:
        service.ensure_sqlite_fts_objects(session)
        tables = session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger') AND name LIKE 'raw_page_chunks_%' ORDER BY name"
            )
        ).scalars().all()
    finally:
        session.close()

    assert "raw_page_chunks_fts" in tables
    assert "raw_page_chunks_ai" in tables
