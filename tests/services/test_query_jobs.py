from __future__ import annotations

import asyncio
import time
from threading import Event

from app.core.config import Settings
from app.db.models import Space, SyncSchedule
from app.db.session import create_session_factory
from app.services.knowledge_service import KnowledgeService
from app.services.query_jobs import QueryJobManager
from app.services.sync_service import SyncCancelledError, SyncResult, SyncService


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met within timeout")


def test_query_job_manager_runs_jobs_fifo_and_reports_queue(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    first_release = Event()
    execution_order: list[tuple[str, str]] = []

    def fake_save_query_wiki(self, *, query: str, selected_space: str | None = None, progress_callback=None):
        execution_order.append(("start", query))
        if progress_callback is not None:
            progress_callback(20, f"{query} 처리 중")
        if query == "첫번째":
            first_release.wait(2)
        execution_order.append(("finish", query))
        return {"href": f"/knowledge/queries/{query}"}

    monkeypatch.setattr(KnowledgeService, "save_query_wiki", fake_save_query_wiki)

    manager = QueryJobManager(settings)
    first = manager.start_job(query="첫번째")
    _wait_until(lambda: (manager.get_job(first["id"]) or {}).get("status") == "running")

    second = manager.start_job(query="두번째")
    second_snapshot = manager.get_job(second["id"])
    assert second_snapshot is not None
    assert second_snapshot["status"] == "queued"

    overview = manager.list_jobs()
    assert overview["running"]["query"] == "첫번째"
    assert [job["query"] for job in overview["queued"]] == ["두번째"]

    first_release.set()
    _wait_until(lambda: (manager.get_job(second["id"]) or {}).get("status") == "completed")

    assert execution_order == [
        ("start", "첫번째"),
        ("finish", "첫번째"),
        ("start", "두번째"),
        ("finish", "두번째"),
    ]


def test_query_job_manager_reuses_existing_active_job(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    release = Event()

    def fake_save_query_wiki(self, *, query: str, selected_space: str | None = None, progress_callback=None):
        if progress_callback is not None:
            progress_callback(15, "처리 중")
        release.wait(2)
        return {"href": f"/knowledge/queries/{query}"}

    monkeypatch.setattr(KnowledgeService, "save_query_wiki", fake_save_query_wiki)

    manager = QueryJobManager(settings)
    first = manager.start_job(query="Codex", selected_space="DEMO")
    _wait_until(lambda: (manager.get_job(first["id"]) or {}).get("status") == "running")

    duplicate = manager.start_job(query="Codex", selected_space="DEMO")

    assert duplicate["id"] == first["id"]
    assert manager.list_jobs()["queued"] == []

    release.set()
    _wait_until(lambda: (manager.get_job(first["id"]) or {}).get("status") == "completed")


def test_query_job_manager_runs_regenerate_job(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    called: list[tuple[str, str, str | None]] = []

    def fake_regenerate_document(self, *, kind: str, slug: str, selected_space: str | None = None):
        called.append((kind, slug, selected_space))
        return {"href": f"/knowledge/keywords/{slug}"}

    monkeypatch.setattr(KnowledgeService, "regenerate_document", fake_regenerate_document)

    manager = QueryJobManager(settings)
    snapshot = manager.start_regenerate_job(
        kind="keyword",
        slug="운영-대시보드",
        title="운영 대시보드",
        selected_space="DEMO",
    )

    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "completed")

    finished = manager.get_job(snapshot["id"])
    assert finished is not None
    assert finished["job_type"] == "regenerate"
    assert finished["kind"] == "keyword"
    assert finished["slug"] == "운영-대시보드"
    assert finished["href"] == "/knowledge/keywords/운영-대시보드"
    assert called == [("keyword", "운영-대시보드", "DEMO")]


def test_query_job_manager_runs_bootstrap_job_with_progress(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    progress_messages: list[str] = []

    async def fake_run_bootstrap_async(self, space_key: str, root_page_id: str, progress_callback=None, cancel_requested=None):
        if progress_callback is not None:
            progress_callback(15, "하위 페이지 트리를 확인하는 중입니다.")
            progress_callback(75, "페이지를 동기화하는 중입니다.")
        progress_messages.append(f"{space_key}:{root_page_id}")
        return SyncResult(mode="bootstrap", space_key=space_key, processed_pages=4, processed_assets=0)

    monkeypatch.setattr(SyncService, "run_bootstrap_async", fake_run_bootstrap_async)

    manager = QueryJobManager(settings)
    snapshot = manager.start_bootstrap_job(space_key="DEMO", root_page_id="9001")

    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "completed")

    finished = manager.get_job(snapshot["id"])
    assert finished is not None
    assert finished["job_type"] == "bootstrap"
    assert finished["space_key"] == "DEMO"
    assert finished["message"] == "Bootstrap이 완료되었습니다."
    assert any(event["message"] == "페이지를 동기화하는 중입니다." for event in finished["events"])
    assert progress_messages == ["DEMO:9001"]


def test_query_job_manager_marks_incremental_schedule_completed(sample_settings_dict, monkeypatch, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    session = create_session_factory(settings.database_url)()
    try:
        space = Space(space_key="DEMO", name="Demo", enabled=True)
        session.add(space)
        session.flush()
        session.add(
            SyncSchedule(
                space_id=space.id,
                schedule_type="incremental",
                enabled=True,
                run_time="03:00",
                timezone="Asia/Seoul",
                last_status="queued",
            )
        )
        session.commit()
    finally:
        session.close()

    async def fake_run_incremental_async(self, space_key: str, progress_callback=None, cancel_requested=None):
        if progress_callback is not None:
            progress_callback(20, "증분 대상 1건을 확인했습니다.")
        return SyncResult(mode="incremental", space_key=space_key, processed_pages=1, processed_assets=0)

    monkeypatch.setattr(SyncService, "run_incremental_async", fake_run_incremental_async)

    manager = QueryJobManager(settings)
    snapshot = manager.start_incremental_job(space_key="DEMO")
    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "completed")

    session = create_session_factory(settings.database_url)()
    try:
        schedule = session.query(SyncSchedule).one()
        assert schedule.last_status == "completed"
        assert schedule.last_error_message is None
    finally:
        session.close()


def test_query_job_manager_can_cancel_queued_sync_job(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    release = Event()

    async def fake_run_bootstrap_async(self, space_key: str, root_page_id: str, progress_callback=None, cancel_requested=None):
        if progress_callback is not None:
            progress_callback(10, "하위 페이지 트리를 확인하는 중입니다.")
        release.wait(2)
        return SyncResult(mode="bootstrap", space_key=space_key, processed_pages=1, processed_assets=0)

    monkeypatch.setattr(SyncService, "run_bootstrap_async", fake_run_bootstrap_async)

    manager = QueryJobManager(settings)
    first = manager.start_bootstrap_job(space_key="OPS", root_page_id="100")
    _wait_until(lambda: (manager.get_job(first["id"]) or {}).get("status") == "running")

    queued = manager.start_bootstrap_job(space_key="DEMO", root_page_id="200")
    queued_snapshot = manager.get_job(queued["id"])
    assert queued_snapshot is not None
    assert queued_snapshot["status"] == "queued"

    cancelled = manager.cancel_job(queued["id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["message"] == "작업을 취소했습니다."
    assert manager.list_jobs(job_types={"bootstrap", "incremental"})["queued"] == []

    release.set()
    _wait_until(lambda: (manager.get_job(first["id"]) or {}).get("status") == "completed")


def test_query_job_manager_can_cancel_running_bootstrap_job(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)

    async def fake_run_bootstrap_async(self, space_key: str, root_page_id: str, progress_callback=None, cancel_requested=None):
        if progress_callback is not None:
            progress_callback(10, "하위 페이지 트리를 확인하는 중입니다.")
        for _ in range(100):
            if cancel_requested is not None and cancel_requested():
                raise SyncCancelledError("cancelled by user")
            await asyncio.sleep(0.01)
        return SyncResult(mode="bootstrap", space_key=space_key, processed_pages=1, processed_assets=0)

    monkeypatch.setattr(SyncService, "run_bootstrap_async", fake_run_bootstrap_async)

    manager = QueryJobManager(settings)
    snapshot = manager.start_bootstrap_job(space_key="DEMO", root_page_id="9001")
    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "running")

    cancel_snapshot = manager.cancel_job(snapshot["id"])
    assert cancel_snapshot["cancel_requested"] is True
    assert cancel_snapshot["message"] == "취소 요청을 보냈습니다."

    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "cancelled")
    finished = manager.get_job(snapshot["id"])
    assert finished is not None
    assert finished["status"] == "cancelled"
    assert finished["message"] == "사용자가 작업을 취소했습니다."

    async def fake_run_incremental_async(self, space_key: str, progress_callback=None, cancel_requested=None):
        return SyncResult(mode="incremental", space_key=space_key, processed_pages=1, processed_assets=0)

    monkeypatch.setattr(SyncService, "run_incremental_async", fake_run_incremental_async)

    session = create_session_factory(settings.database_url)()
    try:
        space = Space(space_key="DEMO", name="Demo", enabled=True)
        session.add(space)
        session.flush()
        session.add(
            SyncSchedule(
                space_id=space.id,
                schedule_type="incremental",
                enabled=True,
                run_time="03:00",
                timezone="Asia/Seoul",
                last_status="queued",
            )
        )
        session.commit()
    finally:
        session.close()

    manager = QueryJobManager(settings)
    snapshot = manager.start_incremental_job(space_key="DEMO")
    _wait_until(lambda: (manager.get_job(snapshot["id"]) or {}).get("status") == "completed")

    session = create_session_factory(settings.database_url)()
    try:
        schedule = session.query(SyncSchedule).one()
        assert schedule.last_status == "completed"
        assert schedule.last_error_message is None
    finally:
        session.close()
