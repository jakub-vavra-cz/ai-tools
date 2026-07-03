# worklog

Last workday git workspace activity for daily agendas.

## Install

```bash
cd dir-worklog
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Optional MCP server: `pip install -e ".[mcp]"`

## CLI

```bash
# Default workspace (GIT_PATH or ~/git), last workday
worklog activity

# Explicit workspaces (repeatable positional)
worklog activity ~/git /data/git --max-repos 12

# Explicit date (ISO 8601 YYYY-MM-DD) or last workday by default
worklog activity --date 2026-06-30

# JSON (same shape as MCP tool)
worklog activity --json

# Today (calendar day, local timezone)
worklog today
worklog today ~/git --max-commits 5 --json

worklog last-workday
```

Inside git repositories, changed files matched by `.gitignore` (and other git exclude rules) are omitted from results. These files are always omitted: `*.log`, `pytest-run.rc`, and `*junit.xml`.

## MCP

Tools: `worklog_workspace_activity`, `worklog_workspace_today`, `worklog_last_workday`.

### Local install

```bash
pip install -e ".[mcp]"
worklog-mcp
```

### Cursor (`~/.cursor/mcp.json`) with uvx

`uvx` installs `worklog` and the `mcp` extra into an isolated tool env on first use. Re-run with `uvx --refresh ...` after upstream changes.

**Local checkout** — adjust the path to your clone:

```json
{
  "mcpServers": {
    "worklog": {
      "command": "uvx",
      "args": [
        "--from",
        "/home/user/git/ai-tools/mcp/dir-worklog[mcp]",
        "worklog-mcp"
      ],
      "env": {
        "GIT_PATH": "/home/user/git"
      }
    }
  }
}
```

**Git HTTPS** — package lives in the `mcp/dir-worklog/` subdirectory of `ai-tools` (pin `@master` or a tag as needed):

```json
{
  "mcpServers": {
    "worklog": {
      "command": "uvx",
      "args": [
        "--from",
        "worklog[mcp] @ git+https://github.com/jakub-vavra-cz/ai-tools#subdirectory=mcp/dir-worklog",
        "worklog-mcp"
      ],
      "env": {
        "GIT_PATH": "/home/user/git"
      }
    }
  }
}
```

Private GitLab hosts may require credentials (`git credential`, `~/.netrc`, or a personal access token in the URL). Tilde paths work in `GIT_PATH`.

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `GIT_PATH` | `~/git` | Default workspace |
| `WORKLOG_MAX_REPOS` | `8` | Default `--max-repos` |
| `WORKLOG_MAX_FILES` | `10` | Default `--max-files` |
| `WORKLOG_MAX_COMMITS` | `10` | Default `--max-commits` |
| `WORKLOG_RECENT_REPOS` | `25` | Default `--recent-repos` |
| `WORKLOG_INCLUDE_SCRATCH` | `0` | Include `@*` dirs when `1` |
