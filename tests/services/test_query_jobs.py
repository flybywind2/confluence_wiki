from __future__ import annotations

import time
from threading import Event

from app.core.config import Settings
from app.services.knowledge_service import KnowledgeService
from app.services.query_jobs import QueryJobManager


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
