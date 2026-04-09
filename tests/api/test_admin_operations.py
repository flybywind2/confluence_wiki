from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.api import routes
from app.core.config import Settings
from app.db.models import Space, SyncSchedule
from app.db.session import create_session_factory
from app.demo_seed import seed_demo_content
from app.main import create_app
from app.services.sync_service import SyncResult, SyncService


def _make_app(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    seed_demo_content(settings=settings)
    app = create_app(settings=settings, allow_test_fallback=False)
    return settings, app


def _login(client: TestClient, role: str = "admin"):
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


def _redirect_error_message(location: str) -> str:
    return parse_qs(urlparse(location).query).get("error", [""])[0]


def test_admin_can_open_operations_page(tmp_path, sample_settings_dict):
    _settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)
    _login(client, "admin")

    response = client.get("/admin/operations")

    assert response.status_code == 200
    assert "운영 관리" in response.text
    assert "Bootstrap 대상" in response.text
    assert "증분 동기화 스케줄" in response.text
    assert "외부 스케줄러" in response.text
    assert 'id="admin-sync-jobs"' in response.text
    assert 'id="admin-sync-current"' in response.text
    assert 'id="admin-sync-progress-fill"' in response.text
    assert 'id="admin-sync-events"' in response.text
    assert 'data-admin-sync-trigger="true"' in response.text
    assert response.text.index("<h2>Bootstrap 대상</h2>") < response.text.index('<section class="history-panel" id="admin-sync-jobs">')


def test_admin_can_register_space_and_save_schedule(tmp_path, sample_settings_dict):
    settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)
    _login(client, "admin")

    create_response = client.post(
        "/admin/spaces",
        data={
            "space_key": "OPS",
            "name": "Operations",
            "root_page_id": "123456",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    schedule_response = client.post(
        "/admin/spaces/OPS/schedule",
        data={
            "enabled": "on",
            "run_time": "03:15",
            "timezone": "Asia/Seoul",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    assert schedule_response.status_code == 303

    session = create_session_factory(settings.database_url)()
    try:
        space = session.scalar(select(Space).where(Space.space_key == "OPS"))
        schedule = session.scalar(select(SyncSchedule).join(Space).where(Space.space_key == "OPS"))
        assert space is not None
        assert space.name == "Operations"
        assert space.root_page_id == "123456"
        assert space.enabled is True
        assert schedule is not None
        assert schedule.enabled is True
        assert schedule.run_time == "03:15"
        assert schedule.timezone == "Asia/Seoul"
    finally:
        session.close()


def test_admin_schedule_save_returns_notice_when_database_is_locked(tmp_path, sample_settings_dict, monkeypatch):
    settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)
    _login(client, "admin")

    session = create_session_factory(settings.database_url)()
    try:
        session.add(Space(space_key="OPS", name="Operations", root_page_id="123456", enabled=True))
        session.commit()
    finally:
        session.close()

    def fake_upsert_schedule(*args, **kwargs):
        raise OperationalError("UPDATE sync_schedules", {}, Exception("database is locked"))

    monkeypatch.setattr(routes.ScheduleService, "upsert_incremental_schedule", fake_upsert_schedule)

    response = client.post(
        "/admin/spaces/OPS/schedule",
        data={"enabled": "on", "run_time": "03:15", "timezone": "Asia/Seoul"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "잠시 후 다시 시도" in _redirect_error_message(response.headers["location"])


def test_admin_space_save_returns_notice_when_database_is_locked(tmp_path, sample_settings_dict, monkeypatch):
    _settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)
    _login(client, "admin")

    def fake_upsert_space(*args, **kwargs):
        raise OperationalError("INSERT INTO spaces", {}, Exception("database is locked"))

    monkeypatch.setattr(routes, "upsert_space", fake_upsert_space)

    response = client.post(
        "/admin/spaces",
        data={"space_key": "OPS", "name": "Operations", "root_page_id": "123456", "enabled": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "잠시 후 다시 시도" in _redirect_error_message(response.headers["location"])


def test_admin_can_trigger_bootstrap_from_operations_ui(tmp_path, sample_settings_dict, monkeypatch):
    settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)
    _login(client, "admin")

    session = create_session_factory(settings.database_url)()
    try:
        session.add(Space(space_key="OPS", name="Operations", root_page_id="123456", enabled=True))
        session.commit()
    finally:
        session.close()

    calls: list[tuple[str, str]] = []

    async def fake_run_bootstrap(self, space_key: str, root_page_id: str):
        calls.append((space_key, root_page_id))
        return SyncResult(mode="bootstrap", space_key=space_key, processed_pages=7, processed_assets=0)

    monkeypatch.setattr(SyncService, "_run_bootstrap", fake_run_bootstrap)

    response = client.post("/admin/spaces/OPS/bootstrap", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/operations")
    assert calls == [("OPS", "123456")]


def test_due_schedule_endpoint_runs_enabled_due_schedules(tmp_path, sample_settings_dict, monkeypatch):
    settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)

    session = create_session_factory(settings.database_url)()
    try:
        ops = Space(space_key="OPS", name="Operations", root_page_id="123456", enabled=True)
        late = Space(space_key="LATE", name="Late Space", root_page_id="999", enabled=True)
        session.add_all([ops, late])
        session.flush()
        session.add_all(
            [
                SyncSchedule(
                    space_id=ops.id,
                    schedule_type="incremental",
                    enabled=True,
                    run_time="00:00",
                    timezone="Asia/Seoul",
                ),
                SyncSchedule(
                    space_id=late.id,
                    schedule_type="incremental",
                    enabled=True,
                    run_time="23:59",
                    timezone="Asia/Seoul",
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    calls: list[str] = []

    async def fake_run_incremental(self, space_key: str, now=None):
        calls.append(space_key)
        return SyncResult(mode="incremental", space_key=space_key, processed_pages=3, processed_assets=0)

    monkeypatch.setattr(SyncService, "_run_incremental", fake_run_incremental)

    response = client.post(
        "/admin/schedules/run-due",
        headers={"X-Admin-Token": settings.sync_admin_token},
        json={"now": "2026-04-09T09:30:00+09:00"},
    )

    assert response.status_code == 200
    assert calls == ["OPS"]
    payload = response.json()
    assert payload["executed_count"] == 1
    assert payload["results"][0]["space_key"] == "OPS"

    session = create_session_factory(settings.database_url)()
    try:
        schedule = session.scalar(select(SyncSchedule).join(Space).where(Space.space_key == "OPS"))
        assert schedule is not None
        assert isinstance(schedule.last_triggered_at, datetime)
        assert schedule.last_status == "completed"
    finally:
        session.close()
