"""Date helpers for git-stats done."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def default_activity_date() -> date:
    return date.today()


def parse_activity_date(value: date | str | None) -> date:
    if value is None:
        return default_activity_date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def activity_window(activity_date: date) -> tuple[datetime, datetime]:
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    start = datetime.combine(activity_date, time.min, tzinfo=local_tz)
    end = start + timedelta(days=1)
    return start, end


def parse_event_time(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def event_on_date(value: str, activity_date: date) -> bool:
    start, end = activity_window(activity_date)
    when = parse_event_time(value)
    return start <= when.astimezone(start.tzinfo) < end
