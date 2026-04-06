from __future__ import annotations

from datetime import datetime, time, timedelta


def build_day_before_yesterday_window(now: datetime) -> tuple[datetime, datetime]:
    target = (now - timedelta(days=2)).date()
    start = datetime.combine(target, time.min, tzinfo=now.tzinfo)
    end = datetime.combine(target, time(23, 59, 59), tzinfo=now.tzinfo)
    return start, end
