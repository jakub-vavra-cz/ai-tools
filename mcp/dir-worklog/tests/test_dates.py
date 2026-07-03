from __future__ import annotations

from datetime import date

from worklog.dates import last_workday, window_bounds


def test_last_workday_from_tuesday():
    assert last_workday(date(2026, 7, 1)) == date(2026, 6, 30)


def test_last_workday_from_monday():
    assert last_workday(date(2026, 7, 6)) == date(2026, 7, 3)


def test_last_workday_from_saturday():
    assert last_workday(date(2026, 7, 4)) == date(2026, 7, 3)


def test_window_bounds_half_open():
    day = date(2026, 6, 30)
    since, until = window_bounds(day)
    assert since.date() == day
    assert until.date() == date(2026, 7, 1)
    assert since < until
