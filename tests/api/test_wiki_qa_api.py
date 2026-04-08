from fastapi.testclient import TestClient

from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.main import create_app


def _login(client: TestClient, role: str = "viewer") -> None:
    password = {
        "viewer": "viewer-pass",
        "editor": "editor-pass",
        "admin": "admin-pass",
    }[role]
    response = client.post(
        "/auth/login",
        data={"username": role, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_wiki_qa_api_answers_within_selected_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.post(
        "/api/ask",
        json={"question": "운영 대시보드가 뭐야?", "scope": "space", "selected_space": "DEMO"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "space"
    assert all("DEMO" in source["space_key"] for source in body["sources"])


def test_wiki_qa_api_can_answer_across_global_wiki(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.post(
        "/api/ask",
        json={"question": "아키텍처 메모는 무엇을 설명해?", "scope": "global", "selected_space": "DEMO"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "global"
    assert any("ARCH" in source["space_key"] for source in body["sources"])


def test_wiki_qa_api_rejects_space_scope_without_specific_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.post(
        "/api/ask",
        json={"question": "질문", "scope": "space", "selected_space": "all"},
    )

    assert response.status_code == 400


def test_wiki_qa_api_can_save_answer_as_analysis_page(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    ask_response = client.post(
        "/api/ask",
        json={"question": "운영 대시보드와 런북 차이를 정리해줘", "scope": "space", "selected_space": "DEMO"},
    )

    assert ask_response.status_code == 200
    payload = ask_response.json()

    save_response = client.post(
        "/api/ask/save",
        json={
            "space_key": "DEMO",
            "question": "운영 대시보드와 런북 차이를 정리해줘",
            "scope": payload["scope"],
            "answer": payload["answer"],
            "sources": payload["sources"],
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["href"].startswith("/knowledge/analyses/")

    analysis_page = client.get(saved["href"])
    assert analysis_page.status_code == 200
    assert "분석 문서" in analysis_page.text
    assert "운영 대시보드와 런북 차이" in analysis_page.text
