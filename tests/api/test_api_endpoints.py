from fastapi.testclient import TestClient

from app.core.config import Settings
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
