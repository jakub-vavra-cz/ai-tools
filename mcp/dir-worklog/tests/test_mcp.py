from __future__ import annotations

from datetime import date

from worklog.mcp_server import _run_workspace_activity


def test_mcp_workspace_today_uses_today(tmp_path):
    ws = tmp_path / "git"
    ws.mkdir()
    result = _run_workspace_activity(
        workspaces=[str(ws)],
        workday=date.today().isoformat(),
        max_repos=8,
        max_files_per_repo=10,
        max_commits_per_repo=0,
        recent_repos_count=5,
        include_scratch_dirs=False,
    )
    assert result["workday"] == date.today().isoformat()
