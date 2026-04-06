from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app


def test_index_page_renders_space_selector():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "space" in response.text.lower()


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
