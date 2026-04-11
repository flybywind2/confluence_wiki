import pytest

from app.core.config import Settings
from app.services.sync_lease import SyncLeaseConflictError
from app.services.sync_service import SyncService
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
