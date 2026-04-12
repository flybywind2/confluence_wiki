from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import SyncLease
from app.services.sync_lease import SyncLeaseConflictError, SyncLeaseService


def test_sync_lease_blocks_second_writer(sample_settings_dict, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    lease_service = SyncLeaseService(settings)

    handle = lease_service.acquire(holder_kind="bootstrap", holder_scope="DEMO")

    with pytest.raises(SyncLeaseConflictError):
        lease_service.acquire(holder_kind="incremental", holder_scope="OPS")

    lease_service.release(handle)
    second = lease_service.acquire(holder_kind="incremental", holder_scope="OPS")
    lease_service.release(second)


def test_sync_lease_can_be_reclaimed_after_expiry(sample_settings_dict, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    lease_service = SyncLeaseService(settings)

    lease_service.acquire(holder_kind="bootstrap", holder_scope="DEMO", ttl_seconds=1)

    session = lease_service.session_factory()
    try:
        lease = session.scalar(select(SyncLease).where(SyncLease.lock_name == lease_service.GLOBAL_SYNC_LOCK))
        assert lease is not None
        lease.expires_at = lease_service._utcnow()
        session.commit()
    finally:
        session.close()

    reclaimed = lease_service.acquire(holder_kind="incremental", holder_scope="OPS", ttl_seconds=60)
    lease_service.release(reclaimed)


def test_sync_lease_can_be_renewed(sample_settings_dict, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    lease_service = SyncLeaseService(settings)

    handle = lease_service.acquire(holder_kind="bootstrap", holder_scope="DEMO", ttl_seconds=60)
    session = lease_service.session_factory()
    try:
        before = session.scalar(select(SyncLease.expires_at).where(SyncLease.owner_id == handle.owner_id))
    finally:
        session.close()

    lease_service.renew(handle)

    session = lease_service.session_factory()
    try:
        after = session.scalar(select(SyncLease.expires_at).where(SyncLease.owner_id == handle.owner_id))
    finally:
        session.close()
    lease_service.release(handle)

    assert before is not None and after is not None
    assert after >= before


def test_sync_lease_can_be_force_released(sample_settings_dict, tmp_path):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
        }
    )
    lease_service = SyncLeaseService(settings)

    handle = lease_service.acquire(holder_kind="bootstrap", holder_scope="DEMO", ttl_seconds=600)

    with pytest.raises(SyncLeaseConflictError):
        lease_service.acquire(holder_kind="incremental", holder_scope="OPS", ttl_seconds=600)

    lease_service.force_release()

    recovered = lease_service.acquire(holder_kind="incremental", holder_scope="OPS", ttl_seconds=600)
    lease_service.release(recovered)
