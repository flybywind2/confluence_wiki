import asyncio

import pytest

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
            progress_callback(20, "첫 번째 단계")
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
