from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock, Thread
from typing import Callable
import uuid

from app.core.config import Settings
from app.db.session import create_session_factory
from app.services.knowledge_service import KnowledgeService
from app.services.schedule_service import ScheduleService
from app.services.sync_service import SyncCancelledError, SyncService

ProgressCallback = Callable[[int, str], None]


@dataclass
class QueryJob:
    id: str
    query: str
    selected_space: str | None
    job_type: str = "query"
    kind: str | None = None
    slug: str | None = None
    space_key: str | None = None
    page_id: str | None = None
    status: str = "queued"
    message: str = "대기 중입니다."
    progress: int = 0
    href: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    events: list[dict[str, object]] = field(default_factory=list)
    cancel_requested: bool = False


class QueryJobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_factory = create_session_factory(settings.database_url)
        self._jobs: dict[str, QueryJob] = {}
        self._pending_job_ids: list[str] = []
        self._running_job_id: str | None = None
        self._worker: Thread | None = None
        self._lock = Lock()

    def start_job(self, *, query: str, selected_space: str | None = None) -> dict[str, object]:
        normalized_query = str(query or "").strip()
        normalized_space = str(selected_space or "").strip() or None
        if not normalized_query:
            raise ValueError("query is required")

        self._prune_old_jobs()
        worker_to_start: Thread | None = None
        with self._lock:
            existing = self._find_active_job_locked(
                job_type="query",
                query=normalized_query,
                selected_space=normalized_space,
            )
            if existing is not None:
                return self._snapshot_locked(existing)

            job = QueryJob(
                id=uuid.uuid4().hex,
                query=normalized_query,
                selected_space=normalized_space,
                message="대기열에 추가되었습니다.",
            )
        return self._enqueue_job(job)

    def start_regenerate_job(
        self,
        *,
        kind: str,
        slug: str,
        title: str | None = None,
        selected_space: str | None = None,
    ) -> dict[str, object]:
        normalized_kind = str(kind or "").strip()
        normalized_slug = str(slug or "").strip()
        normalized_title = str(title or normalized_slug or "").strip()
        normalized_space = str(selected_space or "").strip() or None
        if not normalized_kind or not normalized_slug:
            raise ValueError("kind and slug are required")

        self._prune_old_jobs()
        with self._lock:
            existing = self._find_active_job_locked(
                job_type="regenerate",
                kind=normalized_kind,
                slug=normalized_slug,
                selected_space=normalized_space,
            )
            if existing is not None:
                return self._snapshot_locked(existing)

            job = QueryJob(
                id=uuid.uuid4().hex,
                query=normalized_title,
                selected_space=normalized_space,
                job_type="regenerate",
                kind=normalized_kind,
                slug=normalized_slug,
                message="재작성 대기열에 추가되었습니다.",
            )
        return self._enqueue_job(job)

    def start_sync_job(
        self,
        *,
        mode: str,
        space_key: str,
        root_page_id: str | None = None,
    ) -> dict[str, object]:
        normalized_mode = str(mode or "").strip().lower()
        normalized_space_key = str(space_key or "").strip()
        normalized_page_id = str(root_page_id or "").strip() or None
        if normalized_mode not in {"bootstrap", "incremental"}:
            raise ValueError("mode must be bootstrap or incremental")
        if not normalized_space_key:
            raise ValueError("space_key is required")
        if normalized_mode == "bootstrap" and not normalized_page_id:
            raise ValueError("root_page_id is required for bootstrap")

        self._prune_old_jobs()
        with self._lock:
            existing = self._find_active_job_locked(
                job_type=normalized_mode,
                space_key=normalized_space_key,
            )
            if existing is not None:
                return self._snapshot_locked(existing)
            display_name = f"{normalized_space_key} {'Bootstrap' if normalized_mode == 'bootstrap' else 'Incremental'}"
            job = QueryJob(
                id=uuid.uuid4().hex,
                query=display_name,
                selected_space=normalized_space_key,
                job_type=normalized_mode,
                space_key=normalized_space_key,
                page_id=normalized_page_id,
                message="대기열에 추가되었습니다.",
            )
        return self._enqueue_job(job)

    def start_bootstrap_job(self, *, space_key: str, root_page_id: str) -> dict[str, object]:
        return self.start_sync_job(mode="bootstrap", space_key=space_key, root_page_id=root_page_id)

    def start_incremental_job(self, *, space_key: str) -> dict[str, object]:
        return self.start_sync_job(mode="incremental", space_key=space_key)

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot_locked(job)

    def cancel_job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError("job not found")
            if job.status == "queued":
                job.cancel_requested = True
                job.status = "cancelled"
                job.progress = max(job.progress, 0)
                job.message = "작업을 취소했습니다."
                job.updated_at = datetime.now().isoformat()
                job.events.append(self._event(progress=job.progress, status=job.status, message=job.message))
                self._pending_job_ids = [candidate for candidate in self._pending_job_ids if candidate != job.id]
                return self._snapshot_locked(job)
            if job.status == "running":
                if job.job_type not in {"bootstrap", "incremental"}:
                    raise ValueError("job cannot be cancelled")
                job.cancel_requested = True
                job.message = "취소 요청을 보냈습니다."
                job.updated_at = datetime.now().isoformat()
                if not job.events or job.events[-1].get("message") != job.message:
                    job.events.append(self._event(progress=job.progress, status=job.status, message=job.message))
                return self._snapshot_locked(job)
            return self._snapshot_locked(job)

    def list_jobs(self, *, recent_limit: int = 8, job_types: set[str] | None = None) -> dict[str, object]:
        with self._lock:
            running = None
            if self._running_job_id:
                running_job = self._jobs.get(self._running_job_id)
                if running_job is not None and self._job_visible(running_job, job_types):
                    running = self._snapshot_locked(running_job)

            queued = [
                self._snapshot_locked(job)
                for job_id in self._pending_job_ids
                if (job := self._jobs.get(job_id)) is not None and self._job_visible(job, job_types)
            ]
            recent_jobs = sorted(
                (
                    self._snapshot_locked(job)
                    for job in self._jobs.values()
                    if job.status in {"completed", "failed", "cancelled"} and self._job_visible(job, job_types)
                ),
                key=lambda item: item["updated_at"],
                reverse=True,
            )[:recent_limit]
            return {
                "running": running,
                "queued": queued,
                "recent": recent_jobs,
                "counts": {
                    "running": 1 if running else 0,
                    "queued": len(queued),
                    "recent": len(recent_jobs),
                    "total_active": (1 if running else 0) + len(queued),
                },
            }

    def _enqueue_job(self, job: QueryJob) -> dict[str, object]:
        worker_to_start: Thread | None = None
        with self._lock:
            job.events.append(self._event(progress=0, status="queued", message=job.message))
            self._jobs[job.id] = job
            self._pending_job_ids.append(job.id)
            if self._worker is None or not self._worker.is_alive():
                worker_to_start = Thread(target=self._drain_queue, daemon=True)
                self._worker = worker_to_start
            snapshot = self._snapshot_locked(job)
        if worker_to_start is not None:
            worker_to_start.start()
        return snapshot

    def _drain_queue(self) -> None:
        while True:
            job_to_run: QueryJob | None = None
            with self._lock:
                while self._pending_job_ids and job_to_run is None:
                    next_job_id = self._pending_job_ids.pop(0)
                    candidate = self._jobs.get(next_job_id)
                    if candidate is None:
                        continue
                    if candidate.status != "queued":
                        continue
                    job_to_run = candidate
                    self._running_job_id = candidate.id
                if job_to_run is None:
                    self._worker = None
                    self._running_job_id = None
                    return
            try:
                self._run_job(job_to_run)
            finally:
                with self._lock:
                    if self._running_job_id == job_to_run.id:
                        self._running_job_id = None

    def _run_job(self, job: QueryJob) -> None:
        if job.job_type == "regenerate":
            self._run_regenerate_job(job)
            return
        if job.job_type in {"bootstrap", "incremental"}:
            self._run_sync_job(job)
            return
        self._run_query_job(job)

    def _run_query_job(self, job: QueryJob) -> None:
        self._update(job.id, status="running", progress=5, message="raw 문서를 검색할 준비를 하는 중입니다.")
        try:
            result = KnowledgeService(self.settings).save_query_wiki(
                query=job.query,
                selected_space=job.selected_space,
                progress_callback=lambda progress, message: self._update(
                    job.id,
                    status="running",
                    progress=progress,
                    message=message,
                ),
            )
        except Exception as exc:
            self._update(
                job.id,
                status="failed",
                progress=100,
                message="위키 생성에 실패했습니다.",
                error=str(exc),
            )
            return

        self._update(
            job.id,
            status="completed",
            progress=100,
            message="위키 생성이 완료되었습니다.",
            href=str(result.get("href") or ""),
            error=None,
        )

    def _run_regenerate_job(self, job: QueryJob) -> None:
        self._update(job.id, status="running", progress=5, message="지식 문서를 재작성할 준비를 하는 중입니다.")
        try:
            result = KnowledgeService(self.settings).regenerate_document(
                kind=str(job.kind or ""),
                slug=str(job.slug or ""),
                selected_space=job.selected_space,
            )
        except Exception as exc:
            self._update(
                job.id,
                status="failed",
                progress=100,
                message="지식 재작성에 실패했습니다.",
                error=str(exc),
            )
            return

        self._update(
            job.id,
            status="completed",
            progress=100,
            message="지식 재작성이 완료되었습니다.",
            href=str(result.get("href") or ""),
            error=None,
        )

    def _run_sync_job(self, job: QueryJob) -> None:
        is_bootstrap = job.job_type == "bootstrap"
        start_message = "Bootstrap을 준비하는 중입니다." if is_bootstrap else "증분 동기화를 준비하는 중입니다."
        completed_message = "Bootstrap이 완료되었습니다." if is_bootstrap else "증분 동기화가 완료되었습니다."
        failed_message = "Bootstrap에 실패했습니다." if is_bootstrap else "증분 동기화에 실패했습니다."
        self._update(job.id, status="running", progress=5, message=start_message)
        service = SyncService(self.settings)
        try:
            if is_bootstrap:
                result = asyncio.run(
                    service.run_bootstrap_async(
                        space_key=str(job.space_key or ""),
                        root_page_id=str(job.page_id or ""),
                        progress_callback=lambda progress, message: self._update(
                            job.id,
                            status="running",
                            progress=progress,
                            message=message,
                        ),
                        cancel_requested=lambda: self._is_cancel_requested(job.id),
                    )
                )
            else:
                result = asyncio.run(
                    service.run_incremental_async(
                        space_key=str(job.space_key or ""),
                        progress_callback=lambda progress, message: self._update(
                            job.id,
                            status="running",
                            progress=progress,
                            message=message,
                        ),
                        cancel_requested=lambda: self._is_cancel_requested(job.id),
                    )
                )
        except SyncCancelledError:
            if not is_bootstrap:
                self._record_incremental_schedule_result(
                    space_key=str(job.space_key or ""),
                    status="cancelled",
                    error=None,
                )
            self._update(
                job.id,
                status="cancelled",
                progress=max(job.progress, 1),
                message="사용자가 작업을 취소했습니다.",
                error=None,
            )
            return
        except Exception as exc:
            if not is_bootstrap:
                self._record_incremental_schedule_result(
                    space_key=str(job.space_key or ""),
                    status="failed",
                    error=str(exc),
                )
            self._update(
                job.id,
                status="failed",
                progress=100,
                message=failed_message,
                error=str(exc),
            )
            return
        if not is_bootstrap:
            self._record_incremental_schedule_result(
                space_key=str(job.space_key or ""),
                status="completed",
                error=None,
            )
        self._update(
            job.id,
            status="completed",
            progress=100,
            message=completed_message,
            href=None,
            error=None,
        )

    def _record_incremental_schedule_result(self, *, space_key: str, status: str, error: str | None) -> None:
        if not space_key:
            return
        session = self.session_factory()
        try:
            ScheduleService(self.settings).record_incremental_result(
                session,
                space_key=space_key,
                status=status,
                error=error,
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        href: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = max(0, min(100, int(progress)))
            if message is not None:
                job.message = message
                if not job.events or job.events[-1].get("message") != message or job.events[-1].get("status") != job.status:
                    job.events.append(self._event(progress=job.progress, status=job.status, message=message))
            if href is not None:
                job.href = href or None
            if error is not None:
                job.error = error
            job.updated_at = datetime.now().isoformat()

    def _find_active_job_locked(
        self,
        *,
        job_type: str,
        query: str | None = None,
        kind: str | None = None,
        slug: str | None = None,
        selected_space: str | None = None,
        space_key: str | None = None,
    ) -> QueryJob | None:
        normalized_query = (query or "").casefold()
        normalized_kind = kind or None
        normalized_slug = slug or None
        normalized_space = selected_space or None
        normalized_space_key = space_key or None
        for job in self._jobs.values():
            if job.status not in {"queued", "running"}:
                continue
            if job.job_type != job_type:
                continue
            if job_type == "query" and job.query.casefold() == normalized_query:
                if (job.selected_space or None) != normalized_space:
                    continue
                return job
            if job_type == "regenerate" and (job.kind or None) == normalized_kind and (job.slug or None) == normalized_slug:
                if (job.selected_space or None) != normalized_space:
                    continue
                return job
            if job_type in {"bootstrap", "incremental"} and (job.space_key or None) == normalized_space_key:
                return job
        return None

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancel_requested)

    def _snapshot_locked(self, job: QueryJob) -> dict[str, object]:
        return self._snapshot(
            job,
            queue_position=self._queue_position_locked(job),
        )

    def _queue_position_locked(self, job: QueryJob) -> int | None:
        if job.status == "running":
            return 0
        if job.status != "queued":
            return None
        try:
            return self._pending_job_ids.index(job.id) + 1
        except ValueError:
            return None

    @staticmethod
    def _job_type_label(job_type: str) -> str:
        if job_type == "regenerate":
            return "LLM 재작성"
        if job_type == "bootstrap":
            return "Bootstrap"
        if job_type == "incremental":
            return "증분 동기화"
        return "위키 생성"

    @staticmethod
    def _job_visible(job: QueryJob, job_types: set[str] | None) -> bool:
        if not job_types:
            return True
        return job.job_type in job_types

    @staticmethod
    def _event(*, progress: int, status: str, message: str) -> dict[str, object]:
        return {
            "timestamp": datetime.now().isoformat(),
            "progress": progress,
            "status": status,
            "message": message,
        }

    @staticmethod
    def _snapshot(job: QueryJob, *, queue_position: int | None = None) -> dict[str, object]:
        return {
            "id": job.id,
            "query": job.query,
            "selected_space": job.selected_space,
            "job_type": job.job_type,
            "job_type_label": QueryJobManager._job_type_label(job.job_type),
            "kind": job.kind,
            "slug": job.slug,
            "space_key": job.space_key,
            "page_id": job.page_id,
            "status": job.status,
            "message": job.message,
            "progress": job.progress,
            "queue_position": queue_position,
            "href": job.href,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "events": list(job.events),
            "cancel_requested": job.cancel_requested,
        }

    def _prune_old_jobs(self) -> None:
        cutoff = datetime.now() - timedelta(hours=1)
        with self._lock:
            stale_job_ids = {
                key
                for key, job in self._jobs.items()
                if job.status in {"completed", "failed", "cancelled"} and datetime.fromisoformat(job.updated_at) < cutoff
            }
            for job_id in [
                key
                for key in stale_job_ids
            ]:
                self._jobs.pop(job_id, None)
            if stale_job_ids:
                self._pending_job_ids = [job_id for job_id in self._pending_job_ids if job_id not in stale_job_ids]
