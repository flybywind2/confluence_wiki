from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock, Thread
from typing import Callable
import uuid

from app.core.config import Settings
from app.services.knowledge_service import KnowledgeService

ProgressCallback = Callable[[int, str], None]


@dataclass
class QueryJob:
    id: str
    query: str
    selected_space: str | None
    job_type: str = "query"
    kind: str | None = None
    slug: str | None = None
    status: str = "queued"
    message: str = "대기 중입니다."
    progress: int = 0
    href: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    events: list[dict[str, object]] = field(default_factory=list)


class QueryJobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot_locked(job)

    def list_jobs(self, *, recent_limit: int = 8) -> dict[str, object]:
        with self._lock:
            running = None
            if self._running_job_id:
                running_job = self._jobs.get(self._running_job_id)
                if running_job is not None:
                    running = self._snapshot_locked(running_job)

            queued = [
                self._snapshot_locked(job)
                for job_id in self._pending_job_ids
                if (job := self._jobs.get(job_id)) is not None
            ]
            recent_jobs = sorted(
                (
                    self._snapshot_locked(job)
                    for job in self._jobs.values()
                    if job.status in {"completed", "failed"}
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
    ) -> QueryJob | None:
        normalized_query = (query or "").casefold()
        normalized_kind = kind or None
        normalized_slug = slug or None
        normalized_space = selected_space or None
        for job in self._jobs.values():
            if job.status not in {"queued", "running"}:
                continue
            if job.job_type != job_type:
                continue
            if (job.selected_space or None) != normalized_space:
                continue
            if job_type == "query" and job.query.casefold() == normalized_query:
                return job
            if job_type == "regenerate" and (job.kind or None) == normalized_kind and (job.slug or None) == normalized_slug:
                return job
        return None

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
        return "LLM 재작성" if job_type == "regenerate" else "위키 생성"

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
            "status": job.status,
            "message": job.message,
            "progress": job.progress,
            "queue_position": queue_position,
            "href": job.href,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "events": list(job.events),
        }

    def _prune_old_jobs(self) -> None:
        cutoff = datetime.now() - timedelta(hours=1)
        with self._lock:
            stale_job_ids = {
                key
                for key, job in self._jobs.items()
                if job.status in {"completed", "failed"} and datetime.fromisoformat(job.updated_at) < cutoff
            }
            for job_id in [
                key
                for key in stale_job_ids
            ]:
                self._jobs.pop(job_id, None)
            if stale_job_ids:
                self._pending_job_ids = [job_id for job_id in self._pending_job_ids if job_id not in stale_job_ids]
