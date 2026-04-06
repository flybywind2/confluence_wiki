from fastapi.testclient import TestClient

from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.main import create_app


def test_wiki_qa_api_answers_within_selected_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.post(
        "/api/ask",
        json={"question": "운영 대시보드가 뭐야?", "scope": "space", "selected_space": "DEMO"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "space"
    assert all(source["space_key"] == "DEMO" for source in body["sources"])


def test_wiki_qa_api_can_answer_across_global_wiki(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.post(
        "/api/ask",
        json={"question": "아키텍처 메모는 무엇을 설명해?", "scope": "global", "selected_space": "DEMO"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "global"
    assert any(source["space_key"] == "ARCH" for source in body["sources"])


def test_wiki_qa_api_rejects_space_scope_without_specific_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.post(
        "/api/ask",
        json={"question": "질문", "scope": "space", "selected_space": "all"},
    )

    assert response.status_code == 400
