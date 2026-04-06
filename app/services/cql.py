from __future__ import annotations

from datetime import datetime


def _format_cql_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def build_incremental_cql(space_key: str, start: datetime, end: datetime) -> str:
    start_text = _format_cql_datetime(start)
    end_text = _format_cql_datetime(end)
    return (
        f'space="{space_key}" AND type=page AND '
        f'((created >= "{start_text}" AND created <= "{end_text}") OR '
        f'(lastmodified >= "{start_text}" AND lastmodified <= "{end_text}")) '
        "ORDER BY lastmodified DESC"
    )
