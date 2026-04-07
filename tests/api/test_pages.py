from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Page, PageVersion
from app.db.session import create_session_factory
from app.demo_seed import seed_demo_content
from app.main import app, create_app


def test_index_page_renders_space_selector():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "space" in response.text.lower()
    assert "위키에게 묻기" in response.text


def test_wiki_static_route_serves_space_assets(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    asset_path = tmp_path / "wiki" / "spaces" / "DEMO" / "assets" / "diagram.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"fake-image")

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/wiki-static/spaces/DEMO/assets/diagram.png")

    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_search_page_shows_query_context_and_result_count(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/search?q=런북&space=DEMO")

    assert response.status_code == 200
    assert "검색 결과" in response.text
    assert "런북" in response.text
    assert "핵심 개념" in response.text or "운영과 런북" in response.text


def test_search_page_shows_empty_state_for_no_results(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/search?q=없는문서&space=DEMO")

    assert response.status_code == 200
    assert "검색 결과가 없습니다." in response.text


def test_page_view_renders_breadcrumb_and_meta_description(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO/pages/demo-home-9001")

    assert response.status_code == 200
    assert "전체" in response.text
    assert "DEMO" in response.text
    assert "마지막 동기화 원문 시각" in response.text
    assert '<meta name="description"' in response.text


def test_page_view_exposes_history_navigation(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO/pages/demo-home-9001")

    assert response.status_code == 200
    assert "문서 이력" in response.text
    assert "/spaces/DEMO/pages/demo-home-9001/history" in response.text


def test_history_routes_render_revision_list_and_snapshot(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))

    history = client.get("/spaces/DEMO/pages/demo-home-9001/history")
    assert history.status_code == 200
    assert "버전 1" in history.text

    snapshot = client.get("/spaces/DEMO/pages/demo-home-9001/history/1")
    assert snapshot.status_code == 200
    assert "이전 버전 문서" in snapshot.text
    assert "Confluence Wiki Demo 홈" in snapshot.text


def test_space_home_links_to_synthesis_page(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO")

    assert response.status_code == 200
    assert "/spaces/DEMO/synthesis" in response.text


def test_synthesis_route_renders_space_summary(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO/synthesis")

    assert response.status_code == 200
    assert "DEMO Synthesis" in response.text
    assert "핵심 문서" in response.text


def test_knowledge_route_renders_entity_page(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO/knowledge/entities/demo-home-9001")

    assert response.status_code == 200
    assert "지식 문서" in response.text
    assert "Confluence Wiki Demo 홈" in response.text


def test_history_route_backfills_current_version_when_snapshot_path_is_missing(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    session = create_session_factory(settings.database_url)()
    try:
        page = session.scalar(select(Page).where(Page.slug == "demo-home-9001"))
        version = session.scalar(select(PageVersion).where(PageVersion.page_id == page.id, PageVersion.version_number == 1))
        version.markdown_path = None
        session.commit()
    finally:
        session.close()

    history_file = tmp_path / "wiki" / "spaces" / "DEMO" / "history" / "demo-home-9001" / "v0001.md"
    history_file.unlink()

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/spaces/DEMO/pages/demo-home-9001/history/1")

    assert response.status_code == 200
    assert "이전 버전 문서" in response.text
    assert history_file.exists()
