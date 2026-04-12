from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.models import SyncLease
from app.db.session import create_session_factory


class SyncLeaseConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncLeaseHandle:
    lock_name: str
    owner_id: str
    holder_kind: str
    holder_scope: str
    ttl_seconds: int


class SyncLeaseService:
    GLOBAL_SYNC_LOCK = "sqlite-sync-writer"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_factory = create_session_factory(settings.database_url)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def acquire(self, *, holder_kind: str, holder_scope: str, ttl_seconds: int = 7200) -> SyncLeaseHandle:
        owner_id = uuid4().hex
        handle = SyncLeaseHandle(
            lock_name=self.GLOBAL_SYNC_LOCK,
            owner_id=owner_id,
            holder_kind=holder_kind,
            holder_scope=holder_scope,
            ttl_seconds=ttl_seconds,
        )
        now = self._utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        session = self.session_factory()
        try:
            lease = session.scalar(select(SyncLease).where(SyncLease.lock_name == handle.lock_name))
            if lease is None:
                session.add(
                    SyncLease(
                        lock_name=handle.lock_name,
                        owner_id=handle.owner_id,
                        holder_kind=handle.holder_kind,
                        holder_scope=handle.holder_scope,
                        acquired_at=now,
                        expires_at=expires_at,
                    )
                )
            elif lease.expires_at <= now:
                lease.owner_id = handle.owner_id
                lease.holder_kind = handle.holder_kind
                lease.holder_scope = handle.holder_scope
                lease.acquired_at = now
                lease.expires_at = expires_at
            else:
                raise SyncLeaseConflictError(
                    f"active sync lease held by {lease.holder_kind}:{lease.holder_scope} until {lease.expires_at.isoformat()}"
                )
            session.commit()
            return handle
        except IntegrityError as exc:
            session.rollback()
            raise SyncLeaseConflictError("active sync lease is already held") from exc
        finally:
            session.close()

    def renew(self, handle: SyncLeaseHandle) -> None:
        session = self.session_factory()
        try:
            lease = session.scalar(
                select(SyncLease).where(
                    SyncLease.lock_name == handle.lock_name,
                    SyncLease.owner_id == handle.owner_id,
                )
            )
            if lease is None:
                raise SyncLeaseConflictError("sync lease is missing or owned by another worker")
            lease.expires_at = self._utcnow() + timedelta(seconds=handle.ttl_seconds)
            session.commit()
        finally:
            session.close()

    def get_active_lease(self) -> dict[str, object] | None:
        session = self.session_factory()
        try:
            now = self._utcnow()
            lease = session.scalar(select(SyncLease).where(SyncLease.lock_name == self.GLOBAL_SYNC_LOCK))
            if lease is None:
                return None
            return {
                "lock_name": lease.lock_name,
                "owner_id": lease.owner_id,
                "holder_kind": lease.holder_kind,
                "holder_scope": lease.holder_scope,
                "acquired_at": lease.acquired_at,
                "updated_at": lease.updated_at,
                "expires_at": lease.expires_at,
                "is_expired": lease.expires_at <= now,
            }
        finally:
            session.close()

    def force_release(self) -> bool:
        session = self.session_factory()
        try:
            lease = session.scalar(select(SyncLease).where(SyncLease.lock_name == self.GLOBAL_SYNC_LOCK))
            if lease is None:
                return False
            session.delete(lease)
            session.commit()
            return True
        finally:
            session.close()

    def release(self, handle: SyncLeaseHandle) -> None:
        session = self.session_factory()
        try:
            lease = session.scalar(
                select(SyncLease).where(
                    SyncLease.lock_name == handle.lock_name,
                    SyncLease.owner_id == handle.owner_id,
                )
            )
            if lease is not None:
                session.delete(lease)
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
