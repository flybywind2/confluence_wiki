from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.knowledge import GLOBAL_KNOWLEDGE_SPACE_KEY
from app.db.models import Space, SyncSchedule
from app.services.sync_service import SyncService


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def normalize_run_time(value: str | None) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("run_time is required")
    try:
        hour_value, minute_value = candidate.split(":", 1)
        parsed = time(hour=int(hour_value), minute=int(minute_value))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("run_time must be HH:MM") from exc
    return parsed.strftime("%H:%M")


def normalize_timezone_name(value: str | None, fallback: str) -> str:
    candidate = str(value or "").strip() or fallback
    try:
        ZoneInfo(candidate)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("timezone is invalid") from exc
    return candidate


def _scheduled_local_datetime(now_local: datetime, run_time: str) -> datetime:
    hour_value, minute_value = [int(part) for part in run_time.split(":", 1)]
    return now_local.replace(hour=hour_value, minute=minute_value, second=0, microsecond=0)


def schedule_snapshot(schedule: SyncSchedule, *, now: datetime | None = None) -> dict[str, object]:
    zone = ZoneInfo(schedule.timezone)
    now_aware = now.astimezone(zone) if isinstance(now, datetime) and now.tzinfo else datetime.now(zone)
    scheduled_today = _scheduled_local_datetime(now_aware, schedule.run_time)
    last_triggered_aware = _utc_aware(schedule.last_triggered_at)
    last_triggered_local = last_triggered_aware.astimezone(zone) if last_triggered_aware else None
    due = bool(
        schedule.enabled
        and now_aware >= scheduled_today
        and (last_triggered_local is None or last_triggered_local < scheduled_today)
    )
    if now_aware >= scheduled_today:
        next_run_local = scheduled_today + timedelta(days=1)
    else:
        next_run_local = scheduled_today
    return {
        "id": schedule.id,
        "enabled": schedule.enabled,
        "run_time": schedule.run_time,
        "timezone": schedule.timezone,
        "last_triggered_at": schedule.last_triggered_at,
        "last_status": schedule.last_status or "",
        "last_error_message": schedule.last_error_message or "",
        "due": due,
        "next_run_at": next_run_local.strftime("%Y-%m-%d %H:%M"),
        "last_triggered_label": last_triggered_local.strftime("%Y-%m-%d %H:%M") if last_triggered_local else "-",
    }


@dataclass
class ScheduledRunResult:
    space_key: str
    schedule_id: int
    status: str
    processed_pages: int
    error: str | None = None


class ScheduleService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_or_create_incremental_schedule(self, session: Session, *, space: Space) -> SyncSchedule:
        schedule = session.scalar(
            select(SyncSchedule).where(
                SyncSchedule.space_id == space.id,
                SyncSchedule.schedule_type == "incremental",
            )
        )
        if schedule is None:
            schedule = SyncSchedule(
                space_id=space.id,
                schedule_type="incremental",
                enabled=False,
                run_time="03:00",
                timezone=self.settings.app_timezone,
            )
            session.add(schedule)
            session.flush()
        return schedule

    def upsert_incremental_schedule(
        self,
        session: Session,
        *,
        space: Space,
        enabled: bool,
        run_time: str,
        timezone_name: str | None,
    ) -> SyncSchedule:
        schedule = self.get_or_create_incremental_schedule(session, space=space)
        schedule.enabled = bool(enabled)
        schedule.run_time = normalize_run_time(run_time)
        schedule.timezone = normalize_timezone_name(timezone_name, self.settings.app_timezone)
        session.flush()
        return schedule

    def operations_rows(self, session: Session, *, now: datetime | None = None) -> list[dict[str, object]]:
        spaces = session.scalars(
            select(Space)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
            .order_by(Space.space_key.asc())
        ).all()
        rows: list[dict[str, object]] = []
        for space in spaces:
            schedule = self.get_or_create_incremental_schedule(session, space=space)
            snapshot = schedule_snapshot(schedule, now=now)
            rows.append(
                {
                    "space_key": space.space_key,
                    "name": space.name or space.space_key,
                    "root_page_id": space.root_page_id or "",
                    "enabled": space.enabled,
                    "last_bootstrap_at": space.last_bootstrap_at.strftime("%Y-%m-%d %H:%M") if space.last_bootstrap_at else "-",
                    "last_incremental_at": space.last_incremental_at.strftime("%Y-%m-%d %H:%M") if space.last_incremental_at else "-",
                    "schedule": snapshot,
                }
            )
        session.flush()
        return rows

    async def run_due_incremental_schedules(self, session: Session, *, now: datetime | None = None) -> list[ScheduledRunResult]:
        schedules = session.scalars(
            select(SyncSchedule)
            .join(Space, Space.id == SyncSchedule.space_id)
            .where(
                SyncSchedule.schedule_type == "incremental",
                Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY,
                Space.enabled.is_(True),
                SyncSchedule.enabled.is_(True),
            )
            .order_by(Space.space_key.asc())
        ).all()
        effective_now = now or datetime.now(ZoneInfo(self.settings.app_timezone))
        sync_service = SyncService(settings=self.settings)
        results: list[ScheduledRunResult] = []
        for schedule in schedules:
            snapshot = schedule_snapshot(schedule, now=effective_now)
            if not snapshot["due"]:
                continue
            space = schedule.space
            try:
                result = await sync_service.run_incremental_async(space.space_key, effective_now)
                schedule.last_triggered_at = _utc_naive(datetime.now(timezone.utc))
                schedule.last_status = "completed"
                schedule.last_error_message = None
                session.flush()
                results.append(
                    ScheduledRunResult(
                        space_key=space.space_key,
                        schedule_id=schedule.id,
                        status="completed",
                        processed_pages=result.processed_pages,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                schedule.last_triggered_at = _utc_naive(datetime.now(timezone.utc))
                schedule.last_status = "failed"
                schedule.last_error_message = str(exc)
                session.flush()
                results.append(
                    ScheduledRunResult(
                        space_key=space.space_key,
                        schedule_id=schedule.id,
                        status="failed",
                        processed_pages=0,
                        error=str(exc),
                    )
                )
        return results
