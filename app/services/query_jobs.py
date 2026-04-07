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
        self._lock = Lock()

    def start_job(self, *, query: str, selected_space: str | None = None) -> dict[str, object]:
        normalized_query = str(query or "").strip()
        normalized_space = str(selected_space or "").strip() or None
        if not normalized_query:
            raise ValueError("query is required")

        self._prune_old_jobs()
        job = QueryJob(
            id=uuid.uuid4().hex,
            query=normalized_query,
            selected_space=normalized_space,
        )
        job.events.append(self._event(progress=0, status="queued", message=job.message))
        with self._lock:
            self._jobs[job.id] = job

        worker = Thread(
            target=self._run_job,
            kwargs={"job_id": job.id, "query": normalized_query, "selected_space": normalized_space},
            daemon=True,
        )
        worker.start()
        return self.get_job(job.id) or self._snapshot(job)

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._snapshot(job)

    def _run_job(self, *, job_id: str, query: str, selected_space: str | None) -> None:
        self._update(job_id, status="running", progress=5, message="raw 문서를 검색할 준비를 하는 중입니다.")
        try:
            result = KnowledgeService(self.settings).save_query_wiki(
                query=query,
                selected_space=selected_space,
                progress_callback=lambda progress, message: self._update(
                    job_id,
                    status="running",
                    progress=progress,
                    message=message,
                ),
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                progress=100,
                message="위키 생성에 실패했습니다.",
                error=str(exc),
            )
            return

        self._update(
            job_id,
            status="completed",
            progress=100,
            message="위키 생성이 완료되었습니다.",
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

    @staticmethod
    def _event(*, progress: int, status: str, message: str) -> dict[str, object]:
        return {
            "timestamp": datetime.now().isoformat(),
            "progress": progress,
            "status": status,
            "message": message,
        }

    @staticmethod
    def _snapshot(job: QueryJob) -> dict[str, object]:
        return {
            "id": job.id,
            "query": job.query,
            "selected_space": job.selected_space,
            "status": job.status,
            "message": job.message,
            "progress": job.progress,
            "href": job.href,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "events": list(job.events),
        }

    def _prune_old_jobs(self) -> None:
        cutoff = datetime.now() - timedelta(hours=1)
        with self._lock:
            for job_id in [
                key
                for key, job in self._jobs.items()
                if job.status in {"completed", "failed"} and datetime.fromisoformat(job.updated_at) < cutoff
            ]:
                self._jobs.pop(job_id, None)
