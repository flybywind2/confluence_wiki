from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.cql import build_incremental_cql
from app.services.sync_window import build_day_before_yesterday_window


def test_builds_previous_two_days_window_in_local_timezone():
    now = datetime(2026, 4, 6, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    start, end = build_day_before_yesterday_window(now)

    assert start.isoformat() == "2026-04-04T00:00:00+09:00"
    assert end.isoformat() == "2026-04-04T23:59:59+09:00"


def test_build_incremental_cql_covers_created_and_lastmodified():
    now = datetime(2026, 4, 6, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    start, end = build_day_before_yesterday_window(now)
    cql = build_incremental_cql("DEMO", start, end)

    assert 'space="DEMO"' in cql
    assert "created >=" in cql
    assert "lastmodified >=" in cql
