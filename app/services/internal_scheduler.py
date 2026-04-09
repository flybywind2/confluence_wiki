from __future__ import annotations

import logging
from datetime import datetime

from app.core.config import Settings
from app.db.session import create_session_factory
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)


class InternalScheduleRunner:
    def __init__(self, settings: Settings, query_jobs, session_factory=None) -> None:
        self.settings = settings
        self.query_jobs = query_jobs
        self.session_factory = session_factory or create_session_factory(settings.database_url)

    async def run_once(self, *, now: datetime | None = None) -> list[str]:
        session = self.session_factory()
        try:
            claimed_space_keys = ScheduleService(self.settings).claim_due_incremental_schedules(session, now=now)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        for space_key in claimed_space_keys:
            try:
                self.query_jobs.start_incremental_job(space_key=space_key)
            except Exception:
                logger.exception("failed to enqueue internal incremental schedule for space=%s", space_key)
        return claimed_space_keys
