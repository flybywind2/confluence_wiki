from fastapi.testclient import TestClient

from app.core.config import Settings
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
    assert "동기화 런북" in response.text


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
