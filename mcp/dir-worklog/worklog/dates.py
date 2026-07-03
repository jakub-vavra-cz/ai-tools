"""Workday date helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def last_workday(reference: date | None = None) -> date:
    d = (reference or date.today()) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def window_bounds(workday: date) -> tuple[datetime, datetime]:
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    since = datetime.combine(workday, time.min, tzinfo=local_tz)
    until = since + timedelta(days=1)
    return since, until


def format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.isoformat()
