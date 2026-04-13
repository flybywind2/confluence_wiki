import asyncio

import pytest
from sqlalchemy.exc import OperationalError

import app.services.sync_service as sync_service_module
from app.core.config import Settings
from app.services.sync_lease import SyncLeaseConflictError
from app.services.sync_service import SyncLeaseHandle, SyncService
from app.services.sync_service import SyncPlan


def test_sync_plan_marks_incremental_scope_as_space_wide():
    plan = SyncPlan.for_incremental(space_key="DEMO")

    assert plan.scope == "space"
    assert plan.mode == "incremental"


def test_sync_service_rejects_overlapping_sqlite_sync(sample_settings_dict, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    handle = service.sync_lease_service.acquire(holder_kind="bootstrap", holder_scope="OPS")

    try:
        with pytest.raises(SyncLeaseConflictError):
            service.run_incremental(space_key="DEMO")
    finally:
        service.sync_lease_service.release(handle)


def test_sync_service_renews_lease_while_running(sample_settings_dict, tmp_path, monkeypatch):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    handle = SyncLeaseHandle(
        lock_name="sqlite-sync-writer",
        owner_id="owner-1",
        holder_kind="bootstrap",
        holder_scope="DEMO:test",
        ttl_seconds=300,
    )
    renew_calls: list[str] = []

    monkeypatch.setattr(service.sync_lease_service, "acquire", lambda **kwargs: handle)
    monkeypatch.setattr(service.sync_lease_service, "renew", lambda lease_handle: renew_calls.append(lease_handle.owner_id))
    monkeypatch.setattr(service.sync_lease_service, "release", lambda lease_handle: None)

    async def fake_run_bootstrap(*args, **kwargs):
        progress_callback = kwargs.get("progress_callback")
        if progress_callback is None and len(args) >= 3:
            progress_callback = args[2]
        if progress_callback:
            service._sync_lease_next_renewal_at = service._utcnow()
            progress_callback(20, "첫 번째 단계")
            service._sync_lease_next_renewal_at = service._utcnow()
            progress_callback(50, "두 번째 단계")
        return type("Result", (), {"mode": "bootstrap", "space_key": "DEMO", "processed_pages": 1, "processed_assets": 0})()

    monkeypatch.setattr(service, "_run_bootstrap", fake_run_bootstrap)
    monkeypatch.setattr(service, "_run_post_sync_sqlite_maintenance", lambda: None)

    result = asyncio.run(
        service.run_bootstrap_async(
            "DEMO",
            "1234",
            progress_callback=lambda _progress, _message: None,
        )
    )

    assert result.processed_pages == 1
    assert renew_calls == ["owner-1", "owner-1"]


def test_sync_service_does_not_fail_when_lease_renew_hits_sqlite_lock(sample_settings_dict, tmp_path, monkeypatch):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    service._active_sync_lease = SyncLeaseHandle(
        lock_name="sqlite-sync-writer",
        owner_id="owner-1",
        holder_kind="bootstrap",
        holder_scope="DEMO:test",
        ttl_seconds=300,
    )
    service._sync_lease_next_renewal_at = service._utcnow()

    def raise_locked(_lease_handle):
        raise OperationalError("UPDATE sync_leases", {}, Exception("database is locked"))

    monkeypatch.setattr(service.sync_lease_service, "renew", raise_locked)

    service._renew_sync_lease()


def test_rebuild_materialized_views_emits_stage_progress(sample_settings_dict, tmp_path, monkeypatch):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    session = service.session_factory()
    events: list[tuple[int, str]] = []

    monkeypatch.setattr(
        sync_service_module.KnowledgeService,
        "rebuild_global_with_session",
        lambda self, session, selected_page_ids=None, progress_callback=None, cancel_requested=None: [],
    )
    monkeypatch.setattr(sync_service_module.KnowledgeService, "_rebuild_indexes_for_space", lambda self, session, _space, affected_space_keys=None: None)
    monkeypatch.setattr(sync_service_module.LintService, "rebuild_global_with_session", lambda self, session: None)
    monkeypatch.setattr(sync_service_module, "write_graph_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service_module, "write_named_graph_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service_module, "build_graph_payload", lambda **kwargs: {"nodes": [], "edges": []})
    monkeypatch.setattr(sync_service_module, "build_knowledge_graph_payload", lambda **kwargs: {"nodes": [], "edges": []})

    try:
        service._rebuild_materialized_views(session, progress_callback=lambda progress, message: events.append((progress, message)))
    finally:
        session.close()

    assert events == [
        (93, "지식 문서를 재구성하는 중입니다."),
        (95, "lint 보고서를 재구성하는 중입니다."),
        (97, "인덱스를 재구성하는 중입니다."),
        (99, "그래프 캐시를 재구성하는 중입니다."),
    ]


def test_rebuild_materialized_views_passes_selected_page_ids_to_knowledge_rebuild(sample_settings_dict, tmp_path, monkeypatch):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    session = service.session_factory()
    captured: list[set[int] | None] = []

    monkeypatch.setattr(
        sync_service_module.KnowledgeService,
        "rebuild_global_with_session",
        lambda self, session, selected_page_ids=None, progress_callback=None, cancel_requested=None: captured.append(selected_page_ids) or [],
    )
    monkeypatch.setattr(sync_service_module.KnowledgeService, "_rebuild_indexes_for_space", lambda self, session, _space, affected_space_keys=None: None)
    monkeypatch.setattr(sync_service_module.LintService, "rebuild_global_with_session", lambda self, session: None)
    monkeypatch.setattr(sync_service_module, "write_graph_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service_module, "write_named_graph_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service_module, "build_graph_payload", lambda **kwargs: {"nodes": [], "edges": []})
    monkeypatch.setattr(sync_service_module, "build_knowledge_graph_payload", lambda **kwargs: {"nodes": [], "edges": []})

    try:
        service._rebuild_materialized_views(session, selected_page_ids={1, 2})
    finally:
        session.close()

    assert captured == [{1, 2}]


def test_rebuild_materialized_views_converts_knowledge_cancel_to_sync_cancel(sample_settings_dict, tmp_path, monkeypatch):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    service = SyncService(settings=settings)
    session = service.session_factory()

    def raise_cancel(self, session, selected_page_ids=None, progress_callback=None, cancel_requested=None):
        raise sync_service_module.KnowledgeRebuildCancelledError("knowledge rebuild cancelled")

    monkeypatch.setattr(sync_service_module.KnowledgeService, "rebuild_global_with_session", raise_cancel)

    try:
        with pytest.raises(sync_service_module.SyncCancelledError):
            service._rebuild_materialized_views(session, selected_page_ids={1}, cancel_requested=lambda: True)
    finally:
        session.close()
