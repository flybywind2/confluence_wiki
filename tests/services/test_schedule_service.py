from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import Settings
from app.db.models import Space, SyncSchedule
from app.db.session import create_session_factory
from app.services.internal_scheduler import InternalScheduleRunner
from app.services.schedule_service import ScheduleService


def _settings(tmp_path, sample_settings_dict):
    return Settings.model_validate(
        {
            **sample_settings_dict,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "INTERNAL_SCHEDULER_ENABLED": False,
        }
    )


def test_claim_due_incremental_schedules_marks_schedule_queued(tmp_path, sample_settings_dict):
    settings = _settings(tmp_path, sample_settings_dict)
    session_factory = create_session_factory(settings.database_url)
    session = session_factory()
    try:
        space = Space(space_key="OPS", name="Operations", root_page_id="123456", enabled=True)
        session.add(space)
        session.flush()
        session.add(
            SyncSchedule(
                space_id=space.id,
                schedule_type="incremental",
                enabled=True,
                run_time="03:00",
                timezone="Asia/Seoul",
            )
        )
        session.commit()
    finally:
        session.close()

    session = session_factory()
    try:
        claimed = ScheduleService(settings).claim_due_incremental_schedules(
            session,
            now=datetime.fromisoformat("2026-04-09T09:30:00+09:00"),
        )
        session.commit()
        schedule = session.query(SyncSchedule).one()
        assert claimed == ["OPS"]
        assert schedule.last_status == "queued"
        assert schedule.last_triggered_at is not None
    finally:
        session.close()


def test_internal_scheduler_runner_enqueues_due_incremental_jobs(tmp_path, sample_settings_dict):
    settings = _settings(tmp_path, sample_settings_dict)
    session_factory = create_session_factory(settings.database_url)
    session = session_factory()
    try:
        space = Space(space_key="OPS", name="Operations", root_page_id="123456", enabled=True)
        session.add(space)
        session.flush()
        session.add(
            SyncSchedule(
                space_id=space.id,
                schedule_type="incremental",
                enabled=True,
                run_time="03:00",
                timezone="Asia/Seoul",
            )
        )
        session.commit()
    finally:
        session.close()

    class FakeJobs:
        def __init__(self):
            self.calls: list[str] = []

        def start_incremental_job(self, *, space_key: str):
            self.calls.append(space_key)
            return {"id": "sync-1", "space_key": space_key}

    fake_jobs = FakeJobs()
    runner = InternalScheduleRunner(settings, fake_jobs, session_factory=session_factory)

    claimed = asyncio.run(
        runner.run_once(now=datetime.fromisoformat("2026-04-09T09:30:00+09:00"))
    )

    assert claimed == ["OPS"]
    assert fake_jobs.calls == ["OPS"]
