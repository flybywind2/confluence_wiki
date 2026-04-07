from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_demo_seed_populates_pages_assets_and_graph(tmp_path, sample_settings_dict):
    from app.demo_seed import seed_demo_content

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    result = seed_demo_content(settings)

    assert result["spaces"] == 2
    assert result["pages"] == 4

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))

    home = client.get("/")
    assert home.status_code == 200
    assert "운영" in home.text
    assert "핵심 개념" not in home.text
    assert "ARCH" in home.text

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

    entity_file = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "entities" / "demo-home-9001.md"
    keyword_file = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "운영-대시보드.md"
    unexpected_keyword_files = {
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "td.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "tr.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "th.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "wiki.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "confluence.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "데모.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "graph.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "knowledge.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "view.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "atlas.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "확인합니다.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "1건.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "bootstrap.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "cache.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "hierarchy.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "conf.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "mirror.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "svg.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "url.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "prod.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "ui.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "false.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "예시입니다.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "위주.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "이미지입니다.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "이어지.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "읽기.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "있게.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "즉시.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "증분.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "처리.md",
        tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords" / "호출할.md",
    }
    lint_file = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "lint" / "report.md"
    assert entity_file.exists()
    assert keyword_file.exists()
    assert not any(path.exists() for path in unexpected_keyword_files)
    assert lint_file.exists()

    knowledge_page = client.get("/spaces/DEMO/knowledge/entities/demo-home-9001")
    assert knowledge_page.status_code == 200
    assert "지식 문서" in knowledge_page.text

    lint_page = client.get("/spaces/DEMO/knowledge/lint/report")
    assert lint_page.status_code == 200
    assert "Lint Report" in lint_page.text

    index_text = (tmp_path / "wiki" / "spaces" / "DEMO" / "index.md").read_text(encoding="utf-8")
    assert "## Entities" in index_text
    assert "## Keywords" in index_text
    assert "## Lint" in index_text
    assert "운영 대시보드" in index_text
    assert "핵심 개념" not in index_text

    graph = client.get("/api/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert len(payload["nodes"]) == 4
    assert {edge["type"] for edge in payload["edges"]} == {"hierarchy", "wiki"}
