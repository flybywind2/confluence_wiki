from fastapi.testclient import TestClient

from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.main import app, create_app
from app.services.sync_service import SyncResult, SyncService


def test_graph_endpoint_returns_nodes_and_edges():
    client = TestClient(app)
    response = client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "edges" in body


def test_admin_sync_endpoint_runs_inside_fastapi_event_loop(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    test_app = create_app(settings=settings, allow_test_fallback=False)
    client = TestClient(test_app)

    async def fake_run_incremental(self, space_key: str, now=None):
        return SyncResult(mode="incremental", space_key=space_key, processed_pages=0, processed_assets=0)

    monkeypatch.setattr(SyncService, "_run_incremental", fake_run_incremental)

    response = client.post(
        "/admin/sync",
        headers={"X-Admin-Token": settings.sync_admin_token},
        json={"space": "DEMO"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "incremental"


def test_home_page_shows_knowledge_docs_by_default(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    test_app = create_app(settings=settings, allow_test_fallback=False)
    seed_demo_content(settings=settings)
    client = TestClient(test_app)

    response = client.get("/")

    assert response.status_code == 200
    assert "운영" in response.text
    assert "핵심 개념" not in response.text
    assert "Confluence Wiki Demo 홈" not in response.text
    assert 'href="/spaces/DEMO/pages/ops-dashboard-9002"' not in response.text


def test_search_prefers_knowledge_docs_and_hides_raw_pages_by_default(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    test_app = create_app(settings=settings, allow_test_fallback=False)
    seed_demo_content(settings=settings)
    client = TestClient(test_app)

    response = client.get("/search", params={"q": "런북", "space": "DEMO"})

    assert response.status_code == 200
    assert 'href="/spaces/DEMO/pages/sync-runbook-9003"' not in response.text
    assert 'href="/knowledge/keywords/동기화-런북"' in response.text


def test_graph_endpoint_can_return_knowledge_graph_nodes(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    test_app = create_app(settings=settings, allow_test_fallback=False)
    seed_demo_content(settings=settings)
    client = TestClient(test_app)

    response = client.get("/api/graph", params={"space": "DEMO", "view": "knowledge"})

    assert response.status_code == 200
    payload = response.json()
    assert any(node.get("kind") == "keyword" for node in payload["nodes"])
    assert all(edge["type"] in {"keyword-source", "keyword-related", "analysis-keyword", "synthesis-keyword"} for edge in payload["edges"])


def test_query_generation_creates_query_document(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    test_app = create_app(settings=settings, allow_test_fallback=False)
    seed_demo_content(settings=settings)
    client = TestClient(test_app)

    response = client.post("/api/wiki-from-query", json={"query": "운영 대시보드"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "query"
    assert payload["href"].startswith("/knowledge/queries/")
