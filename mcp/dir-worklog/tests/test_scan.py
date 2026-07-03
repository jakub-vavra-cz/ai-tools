from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

from worklog.dates import window_bounds
from worklog.scan import scan_files


def _touch_in_window(path: Path, workday: date) -> None:
    since, _ = window_bounds(workday)
    ts = (since + timedelta(hours=12)).timestamp()
    os.utime(path, (ts, ts))


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "user@example.com"],
        check=True,
        capture_output=True,
    )


def test_scan_files_respects_gitignore(tmp_path: Path):
    workday = date(2026, 6, 30)
    since, until = window_bounds(workday)
    repo = tmp_path / "myapp"
    repo.mkdir()
    _git_init(repo)
    (repo / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")

    tracked = repo / "src.txt"
    ignored_file = repo / "debug.log"
    ignored_dir = repo / "build" / "out.txt"
    ignored_dir.parent.mkdir()
    tracked.write_text("ok", encoding="utf-8")
    ignored_file.write_text("no", encoding="utf-8")
    ignored_dir.write_text("no", encoding="utf-8")
    _touch_in_window(tracked, workday)
    _touch_in_window(ignored_file, workday)
    _touch_in_window(ignored_dir, workday)

    files, total = scan_files(repo, since=since, until=until, max_files=10)

    paths = {item["path"] for item in files}
    assert total == 1
    assert paths == {"src.txt"}


def test_scan_files_without_git_skips_log_files(tmp_path: Path):
    workday = date(2026, 6, 30)
    since, until = window_bounds(workday)
    repo = tmp_path / "plain"
    repo.mkdir()
    log = repo / "debug.log"
    text = repo / "notes.txt"
    log.write_text("no", encoding="utf-8")
    text.write_text("yes", encoding="utf-8")
    _touch_in_window(log, workday)
    _touch_in_window(text, workday)

    files, total = scan_files(repo, since=since, until=until, max_files=10)

    assert total == 1
    assert files[0]["path"] == "notes.txt"


def test_scan_files_skips_pytest_run_rc_and_junit_xml(tmp_path: Path):
    workday = date(2026, 6, 30)
    since, until = window_bounds(workday)
    repo = tmp_path / "plain"
    repo.mkdir()
    tracked = repo / "notes.txt"
    pytest_rc = repo / "pytest-run.rc"
    junit = repo / "pytests_junit.xml"
    nested_junit = repo / "out" / "results_junit.xml"
    nested_junit.parent.mkdir()
    tracked.write_text("yes", encoding="utf-8")
    pytest_rc.write_text("no", encoding="utf-8")
    junit.write_text("no", encoding="utf-8")
    nested_junit.write_text("no", encoding="utf-8")
    _touch_in_window(tracked, workday)
    _touch_in_window(pytest_rc, workday)
    _touch_in_window(junit, workday)
    _touch_in_window(nested_junit, workday)

    files, total = scan_files(repo, since=since, until=until, max_files=10)

    assert total == 1
    assert files[0]["path"] == "notes.txt"
