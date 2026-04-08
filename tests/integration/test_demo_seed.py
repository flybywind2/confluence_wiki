from fastapi.testclient import TestClient

from app.core.config import Settings
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


def test_demo_seed_populates_pages_assets_and_graph(tmp_path, sample_settings_dict):
    from app.demo_seed import seed_demo_content

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    result = seed_demo_content(settings)

    assert result["spaces"] == 2
    assert result["pages"] == 4

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    home = client.get("/")
    assert home.status_code == 200
    assert "운영" in home.text
    assert "핵심 개념" not in home.text
    assert "Architecture Notes" in home.text

    page = client.get("/spaces/DEMO/pages/demo-home-9001")
    assert page.status_code == 200
    assert "운영 대시보드" in page.text
    assert "atlas-graph.svg" in page.text
    assert "<table>" in page.text

    asset = client.get("/wiki-static/spaces/DEMO/assets/atlas-graph.svg")
    assert asset.status_code == 200
    assert b"svg" in asset.content

    history_index = client.get("/spaces/DEMO/pages/demo-home-9001/history")
    assert history_index.status_code == 200
    assert "버전 1" in history_index.text

    history_file = tmp_path / "wiki" / "spaces" / "DEMO" / "history" / "demo-home-9001" / "v0001.md"
    assert history_file.exists()

    synthesis_file = tmp_path / "wiki" / "spaces" / "DEMO" / "synthesis.md"
    assert synthesis_file.exists()
    assert "# Synthesis" in synthesis_file.read_text(encoding="utf-8")

    keyword_file = tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "운영-대시보드.md"
    unexpected_keyword_files = {
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "td.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "tr.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "th.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "wiki.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "confluence.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "데모.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "graph.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "knowledge.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "view.md",
        tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "atlas.md",
    }
    lint_file = tmp_path / "wiki" / "global" / "knowledge" / "lint" / "report.md"
    assert keyword_file.exists()
    assert not any(path.exists() for path in unexpected_keyword_files)
    assert lint_file.exists()

    knowledge_page = client.get("/knowledge/keywords/운영-대시보드")
    assert knowledge_page.status_code == 200
    assert "키워드 문서" in knowledge_page.text
    assert 'class="inline-source-citation"' in knowledge_page.text
    assert "source-evidence-list" in knowledge_page.text
    assert "2026-04-06" in knowledge_page.text
    assert "2026-04-05" in knowledge_page.text

    lint_page = client.get("/knowledge/lint/report")
    assert lint_page.status_code == 200
    assert "Lint Report" in lint_page.text

    index_text = (tmp_path / "wiki" / "spaces" / "DEMO" / "index.md").read_text(encoding="utf-8")
    assert "## Keywords" in index_text
    assert "## Lint" in index_text
    assert "운영 대시보드" in index_text
    assert "핵심 개념" not in index_text

    graph = client.get("/api/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert len(payload["nodes"]) == 4
    assert {edge["type"] for edge in payload["edges"]} == {"hierarchy", "wiki"}
