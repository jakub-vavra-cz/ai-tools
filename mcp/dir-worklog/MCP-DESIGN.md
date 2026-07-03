# worklog — CLI and MCP design

Design for a **`worklog` CLI** and stdio **MCP server** that implement **agenda §1 — Last workday workspace activity** ([agenda skill](../../.cursor/skills/agenda/SKILL.md)). Replaces ad-hoc shell/`find`/`git log` steps with one structured command or tool call.

**Status:** design only (no implementation in this directory yet).

---

## Goals

- Compute the **previous workday** (Mon–Fri; Monday → prior Friday).
- List git workspace repos whose **top-level directory mtime** falls on that day.
- For each active repo (cap ~8), list **files touched** that day and **git commits** by the repo’s `user.email`.
- When no repo matches the date window, return **recently touched repos** (`ls -ltr` context) so the agenda report still has useful notes.
- Support **multiple workspace roots** in one invocation (repeatable positional `WORKSPACE` on the CLI; `workspaces` array on MCP).

Non-goals for v1: PR/Jira review queues (agenda §2–§3 stay on `gh`/`glab` and `jira-cli` MCP).

---

## Package

| Field | Value |
|-------|-------|
| Package name | `worklog` |
| Python module | `worklog` |
| Console scripts | `worklog` → `worklog.cli:main`; `worklog-mcp` → `worklog.mcp_server:main` |
| Shared core | `worklog.service.workspace_activity()` — used by CLI and MCP |
| MCP transport | stdio (`FastMCP`, same stack as `jira-cli[mcp]` and `git-worktrees-mcp`) |
| Cursor MCP server id (proposed) | `user-worklog` |
| MCP server instructions | Workspace activity for the previous workday. Default workspace: `GIT_PATH` (`~/git`). Pass one or more workspace roots; optional `workday` override. |

### Environment

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GIT_PATH` | No | `~/git` | Default workspace when no `WORKSPACE` positional / empty `workspaces` |
| `WORKLOG_MAX_REPOS` | No | `8` | Default `--max-repos` / `max_repos` |
| `WORKLOG_MAX_FILES` | No | `10` | Default `--max-files` / `max_files_per_repo` |
| `WORKLOG_MAX_COMMITS` | No | `10` | Default `--max-commits` / `max_commits_per_repo` |
| `WORKLOG_RECENT_REPOS` | No | `25` | Default `--recent-repos` / `recent_repos_count` (per workspace) |
| `WORKLOG_INCLUDE_SCRATCH` | No | `0` | Default for `--include-scratch` / `include_scratch_dirs` |

No network or auth required.

### Package layout (implementation target)

```
worklog/
  MCP-DESIGN.md          # this file
  pyproject.toml
  README.md
  worklog/
    __init__.py
    cli.py               # argparse entrypoint
    mcp_server.py        # FastMCP tool registration
    service.py           # workspace_activity() orchestration
    dates.py             # last_workday(), day window bounds
    scan.py              # repo discovery, file walk, git log
    output.py            # human text + JSON serializers
  tools/
    worklog_workspace_activity.json
    worklog_workspace_today.json
    worklog_last_workday.json
```

Dependencies: `mcp>=1.0` (MCP extra only); scanning uses stdlib (`pathlib`, `subprocess` for `git`).

### `pyproject.toml` scripts

```toml
[project.scripts]
worklog = "worklog.cli:main"
worklog-mcp = "worklog.mcp_server:main"

[project.optional-dependencies]
mcp = ["mcp>=1.0"]
```

---

## CLI

Primary user-facing interface. MCP tools call the same `workspace_activity()` function with equivalent parameters.

### Commands

| Command | Purpose |
|---------|---------|
| `worklog activity` | Full workspace scan for a workday |
| `worklog today` | Full workspace scan for today |
| `worklog last-workday` | Print previous Mon–Fri date only |

### `worklog activity`

```bash
worklog activity [WORKSPACE ...] [options]
```

#### Positional: `WORKSPACE` (repeatable)

- **Arity:** zero or more; each value is a directory path (`~` expanded).
- **Default:** when omitted, use a single workspace from `GIT_PATH` (expanded), else `~/git`.
- **Multiple roots:** each `WORKSPACE` is scanned independently; results are merged (see [Multi-workspace merge](#multi-workspace-merge)).

Examples:

```bash
# Default workspace (GIT_PATH or ~/git)
worklog activity

# One explicit root
worklog activity ~/git

# Several roots in one run
worklog activity ~/git /data/git ~/src

worklog activity ~/git ~/worktrees --max-repos 12 --json
```

#### Options

| Flag | Env default | Default | Description |
|------|-------------|---------|-------------|
| `--date DATE` | — | last workday | Activity date, ISO 8601 `YYYY-MM-DD` (`--workday` alias) |
| `--max-repos N` | `WORKLOG_MAX_REPOS` | `8` | Global cap on active repos deep-scanned (files + commits) |
| `--max-files N` | `WORKLOG_MAX_FILES` | `10` | Max files returned per repo |
| `--max-commits N` | `WORKLOG_MAX_COMMITS` | `10` | Max commits per repo (`0` = skip git) |
| `--recent-repos N` | `WORKLOG_RECENT_REPOS` | `25` | Recent top-level dirs **per workspace** for fallback |
| `--include-scratch` | `WORKLOG_INCLUDE_SCRATCH` | off | Include `@*` scratch directories |
| `--json` | — | off | Emit the MCP response dict on stdout |
| `-q` / `--quiet` | — | off | Errors only on stderr (with `--json`, stdout stays clean JSON) |

CLI flags override environment defaults. Unknown workspace paths are recorded in `errors` and skipped (exit `0` if at least one workspace succeeded; exit `2` if every path failed).

#### Human output (default)

When `--json` is not set, print a short report to stdout:

```
workday: 2026-06-30
workspaces: /home/user/git

[myapp] 2 commits, 12 files touched
  a1b2c3d tests: add regression for PROJ-1234
  src/tests/test_foo.py

[my-tools] dir touched, 3 files
  pkg/module.py
```

Group by `workspace_root` when multiple roots were scanned. If `no_activity_on_workday`, append a “recent repos” line per workspace from `recent_repos`.

#### `worklog last-workday`

```bash
worklog last-workday [--reference-date DATE] [--json]
```

Prints one ISO date (previous Mon–Fri relative to `--reference-date` or today). `--json` → `{"workday": "...", "reference_date": "..."}`.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | Usage error, invalid `--workday`, or all workspace paths missing |
| `1` | Reserved for unexpected internal errors |

---

## MCP tools

MCP mirrors the CLI: `worklog_workspace_activity` ≡ `worklog activity`; `worklog_workspace_today` ≡ `worklog today`; `worklog_last_workday` ≡ `worklog last-workday`.

### `worklog_workspace_activity` (primary)

Single call that mirrors `worklog activity`.

#### Parameters

| Name | Type | Default | CLI equivalent |
|------|------|---------|----------------|
| `workspaces` | `list[string]` | `[]` | repeatable `WORKSPACE` positional (empty → `GIT_PATH` / `~/git`) |
| `workday` | `string \| null` | `null` | `--date` / `--workday` |
| `max_repos` | `integer` | `8` | `--max-repos` |
| `max_files_per_repo` | `integer` | `10` | `--max-files` |
| `max_commits_per_repo` | `integer` | `10` | `--max-commits` |
| `recent_repos_count` | `integer` | `25` | `--recent-repos` |
| `include_scratch_dirs` | `boolean` | `false` | `--include-scratch` |

`workspaces` accepts one or more absolute or `~`-expandable paths. Order is preserved in the response; scanning is independent per root.

#### Tool descriptor (`tools/worklog_workspace_activity.json`)

```json
{
  "name": "worklog_workspace_activity",
  "description": "Last workday git workspace activity: repos touched that day, notable files, and your git commits. Same data as agenda skill section 1 (Yesterday).",
  "arguments": {
    "type": "object",
    "properties": {
      "workspaces": {
        "type": "array",
        "items": { "type": "string" },
        "default": [],
        "title": "Workspaces",
        "description": "One or more workspace roots. Empty: GIT_PATH or ~/git."
      },
      "workday": {
        "anyOf": [{ "type": "string" }, { "type": "null" }],
        "default": null,
        "title": "Workday",
        "description": "ISO date (YYYY-MM-DD). Default: previous Mon–Fri workday."
      },
      "max_repos": {
        "default": 8,
        "minimum": 1,
        "maximum": 50,
        "title": "Max Repos",
        "type": "integer"
      },
      "max_files_per_repo": {
        "default": 10,
        "minimum": 1,
        "maximum": 100,
        "title": "Max Files Per Repo",
        "type": "integer"
      },
      "max_commits_per_repo": {
        "default": 10,
        "minimum": 0,
        "maximum": 100,
        "title": "Max Commits Per Repo",
        "type": "integer"
      },
      "recent_repos_count": {
        "default": 25,
        "minimum": 1,
        "maximum": 100,
        "title": "Recent Repos Count",
        "type": "integer"
      },
      "include_scratch_dirs": {
        "default": false,
        "title": "Include Scratch Dirs",
        "type": "boolean",
        "description": "Include @* scratch directories when matching active repos."
      }
    },
    "title": "worklog_workspace_activityArguments"
  },
  "outputSchema": {
    "type": "object",
    "additionalProperties": true,
    "title": "worklog_workspace_activityDictOutput"
  }
}
```

#### Response schema

```json
{
  "workday": "2026-06-30",
  "workspaces": [
    "/home/user/git",
    "/home/user/worktrees"
  ],
  "window": {
    "since": "2026-06-30T00:00:00+02:00",
    "until": "2026-07-01T00:00:00+02:00"
  },
  "active_repos": [
    {
      "workspace_root": "/home/user/git",
      "name": "myapp",
      "path": "/home/user/git/myapp",
      "dir_mtime": "2026-06-30T16:42:11+02:00",
      "is_git": true,
      "files": [
        {
          "path": "src/tests/test_foo.py",
          "mtime": "2026-06-30T15:01:22+02:00"
        }
      ],
      "file_count": 12,
      "commits": [
        {
          "hash": "a1b2c3d",
          "subject": "tests: add regression for PROJ-1234",
          "author_email": "user@example.com"
        }
      ],
      "commit_count": 2
    }
  ],
  "recent_repos": [
    {
      "workspace_root": "/home/user/git",
      "name": "my-tools",
      "path": "/home/user/git/my-tools",
      "dir_mtime": "2026-07-01T06:30:00+02:00"
    }
  ],
  "no_activity_on_workday": false,
  "errors": []
}
```

| Field | Meaning |
|-------|---------|
| `workday` | Resolved calendar day (ISO). |
| `workspaces` | Resolved absolute paths that were scanned (after defaults and `~` expansion). |
| `window.since` / `window.until` | Half-open interval matching agenda `find -newermt` / `git log --since`/`--until`. |
| `active_repos` | Top-level dirs under any workspace with dir mtime in `[since, until)`, deep-scanned up to global `max_repos`. |
| `active_repos[].workspace_root` | Which positional workspace this repo belongs to. |
| `active_repos[].files` | Newest `max_files_per_repo` non-ignored files with mtime in window (sorted desc). |
| `active_repos[].file_count` | Total matching files (may exceed returned slice). |
| `active_repos[].commits` | `git log` oneline rows for repo author email in window. |
| `recent_repos` | Per-workspace fallback: newest `recent_repos_count` top-level dirs each root. |
| `recent_repos[].workspace_root` | Workspace that contained this directory. |
| `no_activity_on_workday` | `true` when `active_repos` is empty across all workspaces. |
| `errors` | Non-fatal issues, e.g. `{"workspace": "/bad/path", "message": "not a directory"}`. |

On fatal errors (invalid `workday`, no valid workspace paths), return `{"ok": false, "error": "..."}`.

---

### `worklog_workspace_today`

Same as `worklog today` — `worklog_workspace_activity` with `workday` fixed to today (local calendar date). Parameters: `workspaces`, `max_repos`, `max_files_per_repo`, `max_commits_per_repo`, `recent_repos_count`, `include_scratch_dirs` (no `workday` argument). Response schema identical to `worklog_workspace_activity`.

Tool descriptor: `tools/worklog_workspace_today.json`.

---

### `worklog_last_workday`

Lightweight tool ≡ `worklog last-workday`.

| Name | Type | Default | CLI equivalent |
|------|------|---------|----------------|
| `reference_date` | `string \| null` | `null` | `--reference-date` |

Response: `{"workday": "2026-06-30", "reference_date": "2026-07-01"}`.

---

## Core API

Both CLI and MCP call:

```python
def workspace_activity(
    *,
    workspaces: list[str] | None = None,
    workday: date | str | None = None,
    max_repos: int = 8,
    max_files_per_repo: int = 10,
    max_commits_per_repo: int = 10,
    recent_repos_count: int = 25,
    include_scratch_dirs: bool = False,
) -> dict[str, Any]: ...
```

- `workspaces is None` or `[]` → resolve `[expand(GIT_PATH or ~/git)]`.
- Otherwise expand each path, validate directories, dedupe by resolved absolute path (preserve first-seen order).
- Return value is identical for `worklog activity --json` and `worklog_workspace_activity`.

## Algorithms

### Last workday (`dates.last_workday`)

Equivalent to agenda skill:

```python
def last_workday(reference: date | None = None) -> date:
    d = (reference or date.today()) - timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d
```

`window_bounds(workday)` → `(since=workday 00:00:00 local, until=workday+1 00:00:00 local)` as timezone-aware datetimes.

### Multi-workspace merge

1. For each resolved workspace root, run [active repo discovery](#active-repo-discovery) and [recent repos fallback](#recent-repos-fallback) independently.
2. Concatenate all candidate active repos; tag each with `workspace_root`.
3. Sort merged candidates by `dir_mtime` ascending; take the last `max_repos` entries globally for file/commit deep scan.
4. Concatenate `recent_repos` from each workspace (each list already capped at `recent_repos_count`).
5. Set `no_activity_on_workday` when the merged active set is empty.

### Active repo discovery

Per workspace root:

1. Error and skip if path is not a directory (append to `errors`).
2. Iterate `workspace.iterdir()` where entry is a directory.
3. Skip names starting with `@` unless `include_scratch_dirs`.
4. Compare `st_mtime` against `[since, until)` (local TZ).
5. Collect all matches (deep-scan cap applied in [multi-workspace merge](#multi-workspace-merge)).

### File scan (per active repo)

Walk with `os.walk` or `pathlib.rglob`, skip:

- `*/.git/*`
- `*/node_modules/*`
- `*/__pycache__/*`
- `*.log`, `pytest-run.rc`, `*junit.xml` (always, even outside git repos)

Collect files with mtime in window; sort by mtime descending; return head `max_files_per_repo`; set `file_count` to full match count.

Inside a **git repository**, drop paths ignored by `.gitignore` (and other git exclude rules) via `git check-ignore --stdin` before counting and slicing. Non-git directories are unchanged.

Prefer Python mtime checks over `find -newermt` for portability; behavior must match agenda half-open day window.

### Git commits (per active repo)

Only when `(repo / ".git").exists()` (file or dir):

```bash
git -C "$REPO" log \
  --since="${SINCE}" --until="${UNTIL}" \
  --oneline --format='%h%x09%s%x09%ae' \
  --author="$(git -C "$REPO" config user.email 2>/dev/null || echo @)" \
  | head -N
```

Parse into `{hash, subject, author_email}`. Empty author config → `--author=@` matches all (same as skill fallback); document that agents should set `user.email` per repo for accurate filtering.

`max_commits_per_repo=0` skips git subprocess entirely.

### Recent repos fallback

Per workspace root: all top-level directories sorted by mtime ascending, last `recent_repos_count` entries (same as `ls -ltr | tail -N`). Tag each with `workspace_root`. Used when `no_activity_on_workday` is true.

---

## Cursor registration

Example `~/.cursor/mcp.json` fragment:

```json
{
  "mcpServers": {
    "worklog": {
      "command": "worklog-mcp",
      "env": {
        "GIT_PATH": "/home/user/git"
      }
    }
  }
}
```

Install: `cd dir-worklog && pip install -e .`

CLI: `worklog activity ~/git` or `worklog activity ~/git /other/root --json`

Invoke from agents: `call_mcp_tool` with `server: "user-worklog"`, `toolName: "worklog_workspace_activity"`, `arguments: {"workspaces": ["/home/user/git"]}`.

---

## Agenda skill integration

Update [agenda/SKILL.md](../../.cursor/skills/agenda/SKILL.md) §1 to prefer MCP when available:

1. `worklog activity` or `call_mcp_tool` → `worklog_workspace_activity` (parallel with GitHub/GitLab/Jira).
2. Map response to report bullets:
   - **Repos:** `active_repos[].name` — prefix with `workspace_root` basename when multiple workspaces; note `commit_count`, `file_count`, or dir mtime.
   - **Notable files:** `active_repos[].files[].path` when useful.
3. If `no_activity_on_workday`, mention recent names from `recent_repos` per workspace.
4. Keep shell fallbacks in the skill when CLI/MCP is unavailable.

Add companion skill `worklog-mcp/SKILL.md` (mirror `jira-cli-mcp`) listing CLI commands, server id, tool names, and response field guide.

---

## Testing notes

- Unit: `last_workday` for Mon/Tue/Sat/Sun reference dates.
- Unit: mtime window boundaries (inclusive since, exclusive until).
- Unit: workspace path expansion, dedupe, and default from `GIT_PATH`.
- Integration: temp workspace with fake repo mtimes and touched files; mock or real git repo for log filtering.
- Integration: two workspace roots in one CLI invocation; `max_repos` applied globally.
- Fixture: Monday run asserts `workday` is prior Friday.

---

## Open questions

1. **Timezone:** Use local system TZ for day boundaries (matches `find -newermt` on the dev machine). Document in README; optional `WORKLOG_TZ` later if needed.
2. **Symlinks:** Treat symlinked top-level entries as directories if `is_dir()`; do not follow symlinked files during walk unless standard practice says otherwise.
3. **Monorepo / nested git:** v1 scans only top-level workspace children, not nested clones inside a repo (same as agenda skill).
4. **Duplicate repo names:** allowed across workspaces; disambiguate with `workspace_root` + `path` in output.
